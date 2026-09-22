package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"deepresearch/internal/api"
	"deepresearch/internal/blob"
	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/db"
	"deepresearch/internal/metrics"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
	"deepresearch/internal/service"
	"deepresearch/internal/sse"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})))
	cfg, err := config.Load()
	if err != nil {
		slog.Error("config", "err", err)
		os.Exit(1)
	}
	d, err := db.Open(cfg.MySQLDSN)
	if err != nil {
		slog.Error("mysql", "err", err)
		os.Exit(1)
	}
	if err := d.Migrate(); err != nil {
		slog.Error("migrate", "err", err)
		os.Exit(1)
	}
	rdb := cache.Open(cfg.RedisAddr)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if err := rdb.Ping(ctx); err != nil {
		slog.Warn("redis unavailable, degraded mode", "err", err)
	}
	cancel()

	producer := mq.NewProducer(cfg.KafkaBrokers)
	hub := sse.New()
	r := repo.New(d)
	store := blob.Open(cfg)
	auth := &service.Auth{Repo: r, Redis: rdb, Cfg: cfg}
	conv := &service.Conversations{Repo: r, Redis: rdb, Producer: producer, Cfg: cfg, Blob: store}
	wakes := service.NewSubagentWakes(r, producer, cfg)
	persist := &service.Persist{Repo: r, OnRunCleared: wakes.OnRunCleared}
	sweep := &service.Sweeper{Repo: r, Producer: producer, Cfg: cfg, Blob: store}

	engine := api.Router(api.Deps{Cfg: cfg, Auth: auth, Conv: conv, Redis: rdb, Hub: hub})
	srv := &http.Server{Addr: cfg.HTTPAddr, Handler: engine}

	root, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go mq.RunLoop(root, mq.NewConsumer(mq.ConsumeOpts{
		Brokers: cfg.KafkaBrokers, Topic: cfg.WakesTopic, GroupID: "go-subagent-wakes",
	}), "subagent-wakes", wakes.Handle)
	go mq.RunLoop(root, mq.NewConsumer(mq.ConsumeOpts{
		Brokers: cfg.KafkaBrokers, Topic: cfg.EventsTopic, GroupID: "go-persist",
	}), "persist", func(ctx context.Context, b []byte) error {
		err := persist.Handle(ctx, b)
		if err == nil {
			metrics.EventsPersisted.Inc()
		}
		return err
	})
	go mq.RunLoop(root, mq.NewConsumer(mq.ConsumeOpts{
		Brokers: cfg.KafkaBrokers, Topic: cfg.EventsTopic,
		GroupID: "go-sse-" + cfg.InstanceID, StartLast: true,
	}), "sse", func(ctx context.Context, b []byte) error {
		ev, err := mq.DecodeEvent(b)
		if err != nil {
			return err
		}
		if ev.Type == "run.finished" {
			if st, ok := ev.Payload["status"].(string); ok {
				metrics.RunsByStatus.WithLabelValues(st).Inc()
			}
		}
		hub.Publish(ev)
		return nil
	})
	go sweep.Run(root)
	go func() {
		t := time.NewTicker(5 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-root.Done():
				return
			case <-t.C:
				metrics.SSEConnections.Set(float64(hub.Connections()))
			}
		}
	}()

	go func() {
		slog.Info("listening", "addr", cfg.HTTPAddr, "instance", cfg.InstanceID)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("http", "err", err)
			os.Exit(1)
		}
	}()
	<-root.Done()
	shut, c := context.WithTimeout(context.Background(), 10*time.Second)
	defer c()
	_ = srv.Shutdown(shut)
	_ = producer.Close()
}

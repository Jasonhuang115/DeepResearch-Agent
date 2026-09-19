package mq

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"time"

	"github.com/segmentio/kafka-go"
)

type Producer struct {
	w *kafka.Writer
}

func NewProducer(brokers []string) *Producer {
	return &Producer{w: &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Balancer:     &kafka.Hash{},
		RequiredAcks: kafka.RequireOne,
		Async:        false,
		BatchTimeout: 10 * time.Millisecond,
		MaxAttempts:  3,
	}}
}

func (p *Producer) Write(ctx context.Context, topic, key string, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return p.w.WriteMessages(ctx, kafka.Message{
		Topic: topic,
		Key:   []byte(key),
		Value: b,
		Time:  time.Now(),
	})
}

func (p *Producer) Close() error { return p.w.Close() }

type Consumer struct {
	r *kafka.Reader
}

type ConsumeOpts struct {
	Brokers   []string
	Topic     string
	GroupID   string
	StartLast bool
}

func NewConsumer(opts ConsumeOpts) *Consumer {
	start := kafka.FirstOffset
	if opts.StartLast {
		start = kafka.LastOffset
	}
	return &Consumer{r: kafka.NewReader(kafka.ReaderConfig{
		Brokers:        opts.Brokers,
		Topic:          opts.Topic,
		GroupID:        opts.GroupID,
		StartOffset:    start,
		MinBytes:       1,
		MaxBytes:       8 << 20,
		CommitInterval: time.Second,
		MaxWait:        500 * time.Millisecond,
	})}
}

func (c *Consumer) Fetch(ctx context.Context) (kafka.Message, error) {
	return c.r.FetchMessage(ctx)
}

func (c *Consumer) Commit(ctx context.Context, m kafka.Message) error {
	return c.r.CommitMessages(ctx, m)
}

func (c *Consumer) Close() error { return c.r.Close() }

func DecodeEvent(b []byte) (Event, error) {
	var ev Event
	err := json.Unmarshal(b, &ev)
	if ev.Payload == nil {
		ev.Payload = map[string]any{}
	}
	return ev, err
}

func RunLoop(ctx context.Context, c *Consumer, name string, fn func(context.Context, []byte) error) {
	for {
		m, err := c.Fetch(ctx)
		if err != nil {
			if ctx.Err() != nil || err == io.EOF {
				return
			}
			slog.Warn("kafka fetch", "consumer", name, "err", err)
			time.Sleep(time.Second)
			continue
		}
		if err := fn(ctx, m.Value); err != nil {
			slog.Error("kafka handle", "consumer", name, "err", err)
		}
		if err := c.Commit(ctx, m); err != nil {
			slog.Warn("kafka commit", "consumer", name, "err", err)
		}
	}
}

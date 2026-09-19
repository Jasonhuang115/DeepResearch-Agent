package service

import (
	"context"
	"log/slog"
	"time"

	"deepresearch/internal/config"
	"deepresearch/internal/model"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
)

type Sweeper struct {
	Repo     *repo.Repo
	Producer *mq.Producer
	Cfg      config.Config
}

func (s *Sweeper) Run(ctx context.Context) {
	t := time.NewTicker(15 * time.Second)
	defer t.Stop()
	s.tick(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			s.tick(ctx)
		}
	}
}

func (s *Sweeper) tick(ctx context.Context) {
	now := time.Now().UTC()
	runs, err := s.Repo.StaleRuns(ctx, now.Add(-s.Cfg.QueuedTimeout), now.Add(-s.Cfg.RunningStale))
	if err != nil {
		slog.Warn("sweeper list", "err", err)
		return
	}
	for _, run := range runs {
		s.fail(ctx, run)
	}
	if n, err := s.Repo.DeleteOldEvents(ctx, now.Add(-s.Cfg.JournalRetention), 1000); err != nil {
		slog.Warn("journal prune", "err", err)
	} else if n > 0 {
		slog.Info("journal pruned", "rows", n)
	}
}

func (s *Sweeper) fail(ctx context.Context, run model.Run) {
	seq, err := s.Repo.MaxSeq(ctx, run.ID)
	if err != nil {
		slog.Warn("sweeper maxseq", "err", err)
		return
	}
	var conv model.Conversation
	if err := s.Repo.DB.System(ctx).Where("id = ?", run.ConversationID).First(&conv).Error; err != nil {
		return
	}
	var ten model.Tenant
	_ = s.Repo.DB.System(ctx).First(&ten, run.TenantID).Error
	base := mq.Event{
		V: 1, RunID: run.PublicID, ConversationID: conv.PublicID, TenantID: ten.PublicID,
		TS: time.Now().UTC(),
	}
	completed := base
	completed.Seq = seq + 1
	completed.Type = "message.completed"
	completed.Payload = map[string]any{"content": "", "truncated": false}
	finished := base
	finished.Seq = seq + 2
	finished.Type = "run.finished"
	finished.Payload = map[string]any{"status": model.RunFailed, "error": "run timed out"}
	if err := s.Producer.Write(ctx, s.Cfg.EventsTopic, conv.PublicID, completed); err != nil {
		slog.Warn("sweeper produce", "err", err, "run", run.PublicID)
		return
	}
	if err := s.Producer.Write(ctx, s.Cfg.EventsTopic, conv.PublicID, finished); err != nil {
		slog.Warn("sweeper produce", "err", err, "run", run.PublicID)
	}
}

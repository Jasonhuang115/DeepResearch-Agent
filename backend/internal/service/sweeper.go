package service

import (
	"context"
	"log/slog"
	"time"

	"deepresearch/internal/blob"
	"deepresearch/internal/config"
	"deepresearch/internal/model"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
)

type Sweeper struct {
	Repo     *repo.Repo
	Producer *mq.Producer
	Cfg      config.Config
	Blob     blob.Store
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
	} else {
		for _, run := range runs {
			if run.Kind == model.RunKindSubagent {
				continue
			}
			s.fail(ctx, run)
		}
	}
	orphanAfter := s.Cfg.SubagentOrphan
	if orphanAfter <= 0 {
		orphanAfter = 2 * time.Hour
	}
	orphans, err := s.Repo.OrphanSubagentRuns(ctx, now.Add(-orphanAfter))
	if err != nil {
		slog.Warn("sweeper subagent list", "err", err)
	} else {
		for _, run := range orphans {
			s.fail(ctx, run)
		}
	}
	if n, err := s.Repo.DeleteOldEvents(ctx, now.Add(-s.Cfg.JournalRetention), 1000); err != nil {
		slog.Warn("journal prune", "err", err)
	} else if n > 0 {
		slog.Info("journal pruned", "rows", n)
	}
	s.gcWorkspaces(ctx, now)
}

func (s *Sweeper) gcWorkspaces(ctx context.Context, now time.Time) {
	if s.Blob == nil || s.Repo == nil {
		return
	}
	retention := s.Cfg.WorkspaceRetention
	if retention <= 0 {
		retention = 168 * time.Hour
	}
	rows, err := s.Repo.IdleConversations(ctx, now.Add(-retention), 200)
	if err != nil {
		slog.Warn("workspace gc list", "err", err)
		return
	}
	if n := PruneSessions(ctx, s.Blob, rows); n > 0 {
		slog.Info("workspace prefixes pruned", "n", n)
	}
}

func PruneSessions(ctx context.Context, store blob.Store, rows []repo.IdleConversation) int {
	if store == nil {
		return 0
	}
	n := 0
	for _, row := range rows {
		if row.TenantPublic == "" || row.ConversationPublic == "" {
			continue
		}
		prefix := blob.SessionPrefix(row.TenantPublic, row.ConversationPublic)
		if err := store.DeletePrefix(ctx, prefix); err != nil {
			slog.Warn("workspace gc", "prefix", prefix, "err", err)
			continue
		}
		n++
	}
	return n
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

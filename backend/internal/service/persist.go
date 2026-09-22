package service

import (
	"context"
	"log/slog"

	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
)

type Persist struct {
	Repo         *repo.Repo
	OnRunCleared func(ctx context.Context, conversationID int64)
}

func (p *Persist) Handle(ctx context.Context, raw []byte) error {
	ev, err := mq.DecodeEvent(raw)
	if err != nil {
		return err
	}
	if ev.RunID == "" || ev.Seq <= 0 {
		return nil
	}
	run, err := p.Repo.RunByPublicSystem(ctx, ev.RunID)
	if err != nil || run == nil {
		slog.Warn("persist unknown run", "run_id", ev.RunID)
		return err
	}
	row := EventToModel(run, ev)
	inserted, err := p.Repo.InsertEvent(ctx, row)
	if err != nil {
		return err
	}
	if !inserted {
		return nil
	}
	asst, clear := ApplySideEffects(run, ev)
	if asst != nil {
		if err := p.Repo.InsertAssistant(ctx, asst); err != nil {
			return err
		}
	}
	if err := p.Repo.SaveRun(ctx, run); err != nil {
		return err
	}
	if clear {
		if err := p.Repo.ClearActiveRun(ctx, run.ConversationID, run.ID); err != nil {
			return err
		}
		if p.OnRunCleared != nil {
			p.OnRunCleared(ctx, run.ConversationID)
		}
	}
	_ = p.Repo.TouchConversation(ctx, run.ConversationID)
	return nil
}

package service

import (
	"context"
	"log/slog"

	"deepresearch/internal/model"
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
	if ev.Type == "subagent.started" {
		if err := p.ensureSubagentRun(ctx, run, ev); err != nil {
			return err
		}
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
		cleared, err := p.Repo.ClearActiveRun(ctx, run.ConversationID, run.ID)
		if err != nil {
			return err
		}
		if notifyCleared(cleared) && p.OnRunCleared != nil {
			p.OnRunCleared(ctx, run.ConversationID)
		}
	}
	_ = p.Repo.TouchConversation(ctx, run.ConversationID)
	return nil
}

func (p *Persist) ensureSubagentRun(ctx context.Context, parent *model.Run, ev mq.Event) error {
	row, err := SubagentRunFromEvent(parent, ev)
	if err != nil {
		slog.Warn("subagent.started ignored", "err", err, "run_id", parent.PublicID)
		return nil
	}
	return p.Repo.CreateSubagentRun(ctx, row)
}

func notifyCleared(cleared bool) bool {
	return cleared
}

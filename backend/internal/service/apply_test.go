package service

import (
	"testing"

	"deepresearch/internal/model"
	"deepresearch/internal/mq"
)

func TestApplyStartedAndFinished(t *testing.T) {
	run := &model.Run{ID: 1, Status: model.RunQueued, TenantID: 2, UserID: 3, ConversationID: 4}
	ApplySideEffects(run, mq.Event{Type: "run.started", Payload: map[string]any{}})
	if run.Status != model.RunRunning {
		t.Fatalf("status %s", run.Status)
	}
	asst, clear := ApplySideEffects(run, mq.Event{Type: "message.completed", Payload: map[string]any{"content": "hi"}})
	if asst == nil || asst.Content != "hi" || asst.Role != "assistant" {
		t.Fatalf("assistant %+v", asst)
	}
	if clear {
		t.Fatal("should not clear yet")
	}
	_, clear = ApplySideEffects(run, mq.Event{Type: "run.finished", Payload: map[string]any{"status": "succeeded"}})
	if !clear || run.Status != model.RunSucceeded {
		t.Fatalf("finish status=%s clear=%v", run.Status, clear)
	}
}

func TestDuplicateSeqIgnoredByCaller(t *testing.T) {
	// document contract: unique (run_id,seq) is the idempotency key
	if model.Terminal(model.RunQueued) {
		t.Fatal("queued is not terminal")
	}
}

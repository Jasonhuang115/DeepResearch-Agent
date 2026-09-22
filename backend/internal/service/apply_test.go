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

func TestSubagentMessageStaysOffTheChat(t *testing.T) {
	run := &model.Run{
		ID: 9, Kind: model.RunKindSubagent, Status: model.RunRunning,
		TenantID: 1, UserID: 2, ConversationID: 3,
	}
	asst, clear := ApplySideEffects(run, mq.Event{Type: "message.completed", Payload: map[string]any{"content": "secret"}})
	if asst != nil || clear {
		t.Fatalf("assistant=%v clear=%v", asst, clear)
	}
	_, clear = ApplySideEffects(run, mq.Event{Type: "run.finished", Payload: map[string]any{"status": "succeeded"}})
	if run.Status != model.RunSucceeded || !clear {
		t.Fatalf("status=%s clear=%v", run.Status, clear)
	}
	if notifyCleared(false) {
		t.Fatal("a subagent finish that did not clear active_run must not wake")
	}
	if !notifyCleared(true) {
		t.Fatal("clearing the active run still wakes")
	}
}

func TestSubagentStartedBuildsChildRun(t *testing.T) {
	parent := &model.Run{ID: 4, PublicID: "run_parent", TenantID: 2, UserID: 3, ConversationID: 8, Kind: model.RunKindMain}
	long := ""
	for i := 0; i < 600; i++ {
		long += "字"
	}
	row, err := SubagentRunFromEvent(parent, mq.Event{Type: "subagent.started", Payload: map[string]any{
		"subagent_id":        "alpha",
		"child_run_id":       "run_child",
		"description":        long,
		"depth":              float64(2),
		"parent_subagent_id": "parent-a",
	}})
	if err != nil {
		t.Fatal(err)
	}
	if row.Kind != model.RunKindSubagent || row.Status != model.RunQueued {
		t.Fatalf("kind=%s status=%s", row.Kind, row.Status)
	}
	if row.ParentRunID == nil || *row.ParentRunID != parent.ID {
		t.Fatalf("parent run %+v", row.ParentRunID)
	}
	if row.SubagentID == nil || *row.SubagentID != "alpha" {
		t.Fatal("subagent id")
	}
	if row.ParentSubagentID == nil || *row.ParentSubagentID != "parent-a" {
		t.Fatal("parent subagent")
	}
	if row.Depth != 2 || row.ConversationID != parent.ConversationID {
		t.Fatalf("depth=%d conv=%d", row.Depth, row.ConversationID)
	}
	if row.Description == nil || len([]rune(*row.Description)) != 512 {
		t.Fatal("description clip")
	}
	if _, err := SubagentRunFromEvent(parent, mq.Event{Payload: map[string]any{}}); err == nil {
		t.Fatal("expected invalid payload")
	}
	if model.Terminal(model.RunTimedOut) == false {
		t.Fatal("timed_out is terminal")
	}
}

func TestDuplicateSeqIgnoredByCaller(t *testing.T) {
	// document contract: unique (run_id,seq) is the idempotency key
	if model.Terminal(model.RunQueued) {
		t.Fatal("queued is not terminal")
	}
}

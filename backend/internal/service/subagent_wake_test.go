package service

import (
	"encoding/json"
	"testing"

	"deepresearch/internal/model"
	"deepresearch/internal/mq"
)

func TestWakeQueueCoalescesAndRestores(t *testing.T) {
	q := newWakeQueue()
	q.add("conv_1", "ten_a", "usr_a", mq.WakeReport{ID: "alpha", Status: "succeeded", ReportPath: "subagents/alpha/report.md"})
	q.add("conv_1", "ten_a", "usr_a", mq.WakeReport{ID: "beta", Status: "timed_out", ReportPath: "subagents/beta/report.md"})
	q.add("conv_1", "ten_a", "usr_a", mq.WakeReport{ID: "alpha", Status: "failed", ReportPath: "subagents/alpha/report.md"})

	batch := q.take("conv_1")
	if batch == nil || len(batch.Reports) != 2 {
		t.Fatalf("batch %+v", batch)
	}
	if batch.Reports[0].ID != "alpha" || batch.Reports[0].Status != "failed" {
		t.Fatalf("alpha was not updated: %+v", batch.Reports[0])
	}
	if batch.Reports[1].ID != "beta" {
		t.Fatalf("beta missing: %+v", batch.Reports)
	}
	if again := q.take("conv_1"); again != nil {
		t.Fatalf("second take %+v", again)
	}

	q.add("conv_1", "ten_a", "usr_a", mq.WakeReport{ID: "gamma", Status: "succeeded", ReportPath: "subagents/gamma/report.md"})
	q.restore("conv_1", batch)
	merged := q.take("conv_1")
	if merged == nil || len(merged.Reports) != 3 {
		t.Fatalf("merged %+v", merged)
	}
	if merged.Reports[0].ID != "alpha" || merged.Reports[2].ID != "gamma" {
		t.Fatalf("order %+v", merged.Reports)
	}
}

func TestBuildWakeCommandHasNoUserBubble(t *testing.T) {
	conv := &model.Conversation{PublicID: "conv_1"}
	history := []model.Message{{PublicID: "msg_1", Role: "user", Content: "固态电池"}}
	reports := []mq.WakeReport{
		{ID: "alpha", Status: "succeeded", ReportPath: "subagents/alpha/report.md"},
		{ID: "beta", Status: "timed_out", ReportPath: "subagents/beta/report.md"},
	}
	cmd := BuildWakeCommand(conv, "ten_a", "usr_a", "run_wake", history, reports, 80000)
	if cmd.Type != "start" || cmd.Request == nil || cmd.Request.Content != "" {
		t.Fatalf("request %+v", cmd.Request)
	}
	if cmd.Wake == nil || len(cmd.Wake.Reports) != 2 {
		t.Fatalf("wake %+v", cmd.Wake)
	}
	if len(cmd.Messages) != 1 || cmd.Messages[0].Role != "user" || cmd.Messages[0].Content != "固态电池" {
		t.Fatalf("messages %+v", cmd.Messages)
	}
	raw, err := json.Marshal(cmd)
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	wake := decoded["wake"].(map[string]any)
	rows := wake["reports"].([]any)
	first := rows[0].(map[string]any)
	if first["report_path"] != "subagents/alpha/report.md" {
		t.Fatalf("payload %s", raw)
	}
}

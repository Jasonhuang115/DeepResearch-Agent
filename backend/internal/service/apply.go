package service

import (
	"encoding/json"
	"time"

	"gorm.io/datatypes"

	"deepresearch/internal/id"
	"deepresearch/internal/model"
	"deepresearch/internal/mq"
)

func payloadStatus(p map[string]any) (string, *string) {
	st, _ := p["status"].(string)
	var errMsg *string
	if e, ok := p["error"].(string); ok && e != "" {
		errMsg = &e
	}
	return st, errMsg
}

func payloadContent(p map[string]any) string {
	c, _ := p["content"].(string)
	return c
}

func ApplySideEffects(run *model.Run, ev mq.Event) (assistant *model.Message, clearActive bool) {
	now := ev.TS
	if now.IsZero() {
		now = time.Now().UTC()
	}
	run.LastEventAt = &now
	switch ev.Type {
	case "run.started":
		if run.Status == model.RunQueued {
			run.Status = model.RunRunning
		}
	case "message.completed":
		content := payloadContent(ev.Payload)
		assistant = &model.Message{
			PublicID:       id.New("msg_"),
			TenantID:       run.TenantID,
			UserID:         run.UserID,
			ConversationID: run.ConversationID,
			RunID:          &run.ID,
			Role:           "assistant",
			Content:        content,
		}
	case "run.finished":
		st, errMsg := payloadStatus(ev.Payload)
		if st == "" {
			st = model.RunFailed
		}
		run.Status = st
		run.ErrorMessage = errMsg
		clearActive = true
	}
	return assistant, clearActive
}

func EventToModel(run *model.Run, ev mq.Event) *model.RunEvent {
	b, _ := json.Marshal(ev.Payload)
	if len(b) == 0 {
		b = []byte("{}")
	}
	return &model.RunEvent{
		TenantID:       run.TenantID,
		UserID:         run.UserID,
		RunID:          run.ID,
		ConversationID: run.ConversationID,
		Seq:            ev.Seq,
		Type:           ev.Type,
		Payload:        datatypes.JSON(b),
		CreatedAt:      ev.TS,
	}
}

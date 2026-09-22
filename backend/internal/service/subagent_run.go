package service

import (
	"errors"
	"unicode/utf8"

	"deepresearch/internal/model"
	"deepresearch/internal/mq"
)

var errSubagentEvent = errors.New("invalid subagent.started")

func SubagentRunFromEvent(parent *model.Run, ev mq.Event) (*model.Run, error) {
	if parent == nil {
		return nil, errSubagentEvent
	}
	childID, _ := ev.Payload["child_run_id"].(string)
	subID, _ := ev.Payload["subagent_id"].(string)
	if childID == "" || len(childID) > 40 || subID == "" || len(subID) > 64 {
		return nil, errSubagentEvent
	}
	desc := clipRunes(payloadString(ev.Payload, "description"), 512)
	var descPtr *string
	if desc != "" {
		descPtr = &desc
	}
	var parentSub *string
	if s := payloadString(ev.Payload, "parent_subagent_id"); s != "" {
		if len(s) > 64 {
			return nil, errSubagentEvent
		}
		parentSub = &s
	}
	depth := payloadDepth(ev.Payload["depth"])
	if depth < 1 {
		depth = 1
	}
	parentID := parent.ID
	return &model.Run{
		PublicID:         childID,
		TenantID:         parent.TenantID,
		UserID:           parent.UserID,
		ConversationID:   parent.ConversationID,
		Status:           model.RunQueued,
		Kind:             model.RunKindSubagent,
		SubagentID:       &subID,
		ParentRunID:      &parentID,
		ParentSubagentID: parentSub,
		Description:      descPtr,
		Depth:            depth,
	}, nil
}

func payloadString(p map[string]any, key string) string {
	s, _ := p[key].(string)
	return s
}

func payloadDepth(raw any) int {
	switch d := raw.(type) {
	case float64:
		return int(d)
	case int:
		return d
	case int64:
		return int(d)
	default:
		return 0
	}
}

func clipRunes(s string, n int) string {
	if n <= 0 || utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}

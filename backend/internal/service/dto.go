package service

import (
	"time"
	"unicode/utf8"

	"deepresearch/internal/model"
)

type ConversationView struct {
	ID        string   `json:"id"`
	Title     string   `json:"title"`
	ActiveRun *RunView `json:"active_run"`
	UpdatedAt string   `json:"updated_at"`
	CreatedAt string   `json:"created_at"`
}

type RunView struct {
	ID             string  `json:"id"`
	ConversationID string  `json:"conversation_id,omitempty"`
	Status         string  `json:"status"`
	Error          *string `json:"error,omitempty"`
}

type MessageView struct {
	ID             string           `json:"id"`
	ConversationID string           `json:"conversation_id"`
	RunID          *string          `json:"run_id,omitempty"`
	Role           string           `json:"role"`
	Content        string           `json:"content"`
	Attachments    []AttachmentView `json:"attachments,omitempty"`
	CreatedAt      string           `json:"created_at"`
}

type AttachmentView struct {
	ID          string `json:"id"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	Size        int64  `json:"size"`
}

type ListOut[T any] struct {
	Items      []T     `json:"items"`
	NextBefore *string `json:"next_before"`
}

func convView(c model.Conversation, run *model.Run) ConversationView {
	v := ConversationView{
		ID:        c.PublicID,
		Title:     c.Title,
		UpdatedAt: c.UpdatedAt.UTC().Format(time.RFC3339Nano),
		CreatedAt: c.CreatedAt.UTC().Format(time.RFC3339Nano),
	}
	if run != nil {
		rv := RunView{ID: run.PublicID, ConversationID: c.PublicID, Status: run.Status, Error: run.ErrorMessage}
		v.ActiveRun = &rv
	}
	return v
}

func msgView(m model.Message, convPublic string, runPublic *string, atts []model.Attachment) MessageView {
	v := MessageView{
		ID:             m.PublicID,
		ConversationID: convPublic,
		RunID:          runPublic,
		Role:           m.Role,
		Content:        m.Content,
		CreatedAt:      m.CreatedAt.UTC().Format(time.RFC3339Nano),
	}
	if len(atts) > 0 {
		v.Attachments = make([]AttachmentView, 0, len(atts))
		for _, a := range atts {
			v.Attachments = append(v.Attachments, AttachmentView{
				ID: a.PublicID, Filename: a.Filename, ContentType: a.ContentType, Size: a.SizeBytes,
			})
		}
	}
	return v
}

type SubagentView struct {
	ID          string  `json:"id"`
	RunID       string  `json:"run_id"`
	ParentRunID string  `json:"parent_run_id"`
	ParentID    *string `json:"parent_id"`
	Description string  `json:"description"`
	Status      string  `json:"status"`
	Depth       int     `json:"depth"`
}

func subagentView(row model.Run, parentPublic string) SubagentView {
	id := ""
	if row.SubagentID != nil {
		id = *row.SubagentID
	}
	desc := ""
	if row.Description != nil {
		desc = *row.Description
	}
	return SubagentView{
		ID:          id,
		RunID:       row.PublicID,
		ParentRunID: parentPublic,
		ParentID:    row.ParentSubagentID,
		Description: desc,
		Status:      row.Status,
		Depth:       row.Depth,
	}
}

func runView(r model.Run, convPublic string) RunView {
	return RunView{ID: r.PublicID, ConversationID: convPublic, Status: r.Status, Error: r.ErrorMessage}
}

func titleFrom(content string) string {
	rs := []rune(content)
	if len(rs) > 30 {
		return string(rs[:30])
	}
	if utf8.RuneCountInString(content) == 0 {
		return "Untitled"
	}
	return content
}

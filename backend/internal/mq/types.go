package mq

import "time"

type Command struct {
	V              int       `json:"v"`
	Type           string    `json:"type"`
	RunID          string    `json:"run_id"`
	ConversationID string    `json:"conversation_id"`
	TenantID       string    `json:"tenant_id"`
	UserID         string    `json:"user_id,omitempty"`
	Request        *Request  `json:"request,omitempty"`
	Messages       []Msg     `json:"messages,omitempty"`
	Wake           *Wake     `json:"wake,omitempty"`
	Reason         string    `json:"reason,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

type Wake struct {
	Reports []WakeReport `json:"reports"`
}

type WakeReport struct {
	ID         string `json:"id"`
	Status     string `json:"status"`
	ReportPath string `json:"report_path"`
}

type SubagentWake struct {
	V              int    `json:"v"`
	ConversationID string `json:"conversation_id"`
	TenantID       string `json:"tenant_id"`
	UserID         string `json:"user_id"`
	ID             string `json:"id"`
	Status         string `json:"status"`
	ReportPath     string `json:"report_path"`
}

type Request struct {
	Content     string          `json:"content"`
	Attachments []AttachmentRef `json:"attachments,omitempty"`
}

type AttachmentRef struct {
	ID          string `json:"id"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	Path        string `json:"path"`
	Size        int64  `json:"size"`
}

type Msg struct {
	ID      string `json:"id"`
	Role    string `json:"role"`
	Content string `json:"content"`
}

type Event struct {
	V              int            `json:"v"`
	RunID          string         `json:"run_id"`
	ConversationID string         `json:"conversation_id"`
	TenantID       string         `json:"tenant_id"`
	Seq            int64          `json:"seq"`
	Type           string         `json:"type"`
	Payload        map[string]any `json:"payload"`
	TS             time.Time      `json:"ts"`
}

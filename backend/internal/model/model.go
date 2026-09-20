package model

import (
	"time"

	"gorm.io/datatypes"
)

type Tenant struct {
	ID        int64     `gorm:"primaryKey"`
	PublicID  string    `gorm:"column:public_id;size:40;uniqueIndex"`
	Name      string    `gorm:"size:128"`
	CreatedAt time.Time `gorm:"autoCreateTime"`
	UpdatedAt time.Time `gorm:"autoUpdateTime"`
}

func (Tenant) TableName() string { return "tenants" }

type User struct {
	ID           int64     `gorm:"primaryKey"`
	PublicID     string    `gorm:"column:public_id;size:40;uniqueIndex"`
	TenantID     int64     `gorm:"index"`
	Email        string    `gorm:"size:255;uniqueIndex"`
	DisplayName  string    `gorm:"size:128"`
	PasswordHash string    `gorm:"column:password_hash"`
	Role         string    `gorm:"size:32"`
	CreatedAt    time.Time `gorm:"autoCreateTime"`
	UpdatedAt    time.Time `gorm:"autoUpdateTime"`
}

func (User) TableName() string { return "users" }

type Conversation struct {
	ID          int64      `gorm:"primaryKey"`
	PublicID    string     `gorm:"column:public_id;size:40;uniqueIndex"`
	TenantID    int64      `gorm:"index"`
	UserID      int64      `gorm:"index"`
	Title       string     `gorm:"size:255"`
	ActiveRunID *int64     `gorm:"column:active_run_id"`
	DeletedAt   *time.Time `gorm:"index"`
	CreatedAt   time.Time  `gorm:"autoCreateTime"`
	UpdatedAt   time.Time  `gorm:"autoUpdateTime"`
}

func (Conversation) TableName() string { return "conversations" }

const (
	RunQueued    = "queued"
	RunRunning   = "running"
	RunSucceeded = "succeeded"
	RunFailed    = "failed"
	RunCancelled = "cancelled"
)

func Terminal(status string) bool {
	return status == RunSucceeded || status == RunFailed || status == RunCancelled
}

type Run struct {
	ID             int64      `gorm:"primaryKey"`
	PublicID       string     `gorm:"column:public_id;size:40;uniqueIndex"`
	TenantID       int64      `gorm:"index"`
	UserID         int64      `gorm:"index"`
	ConversationID int64      `gorm:"index"`
	Status         string     `gorm:"size:24"`
	ErrorMessage   *string    `gorm:"column:error_message"`
	LastEventAt    *time.Time `gorm:"column:last_event_at"`
	CreatedAt      time.Time  `gorm:"autoCreateTime"`
	UpdatedAt      time.Time  `gorm:"autoUpdateTime"`
}

func (Run) TableName() string { return "runs" }

type Message struct {
	ID             int64     `gorm:"primaryKey"`
	PublicID       string    `gorm:"column:public_id;size:40;uniqueIndex"`
	TenantID       int64     `gorm:"index"`
	UserID         int64     `gorm:"index"`
	ConversationID int64     `gorm:"index"`
	RunID          *int64    `gorm:"column:run_id;uniqueIndex:uk_msg_run_role"`
	Role           string    `gorm:"size:16;uniqueIndex:uk_msg_run_role"`
	Content        string    `gorm:"type:mediumtext"`
	CreatedAt      time.Time `gorm:"autoCreateTime"`
}

func (Message) TableName() string { return "messages" }

type Attachment struct {
	ID             int64     `gorm:"primaryKey"`
	PublicID       string    `gorm:"column:public_id;size:40;uniqueIndex"`
	TenantID       int64     `gorm:"index"`
	UserID         int64     `gorm:"index"`
	ConversationID int64     `gorm:"index"`
	MessageID      int64     `gorm:"column:message_id;index"`
	Filename       string    `gorm:"size:255"`
	ContentType    string    `gorm:"column:content_type;size:127"`
	SizeBytes      int64     `gorm:"column:size_bytes"`
	SHA256         string    `gorm:"column:sha256;size:64"`
	StoragePath    string    `gorm:"column:storage_path;size:512"`
	CreatedAt      time.Time `gorm:"autoCreateTime"`
}

func (Attachment) TableName() string { return "attachments" }

type RunEvent struct {
	ID             int64          `gorm:"primaryKey"`
	TenantID       int64          `gorm:"index"`
	UserID         int64          `gorm:"index"`
	RunID          int64          `gorm:"uniqueIndex:uk_run_seq"`
	ConversationID int64          `gorm:"index"`
	Seq            int64          `gorm:"uniqueIndex:uk_run_seq"`
	Type           string         `gorm:"size:64"`
	Payload        datatypes.JSON `gorm:"type:json"`
	CreatedAt      time.Time      `gorm:"autoCreateTime"`
}

func (RunEvent) TableName() string { return "run_events" }

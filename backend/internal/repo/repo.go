package repo

import (
	"context"
	"errors"
	"time"

	"gorm.io/gorm"

	"deepresearch/internal/db"
	"deepresearch/internal/model"
	"deepresearch/internal/tenant"
)

type Repo struct {
	DB *db.DB
}

func New(d *db.DB) *Repo { return &Repo{DB: d} }

func (r *Repo) scoped(ctx context.Context) *gorm.DB { return r.DB.Scoped(ctx) }
func (r *Repo) sys(ctx context.Context) *gorm.DB    { return r.DB.System(ctx) }

func (r *Repo) CreateTenant(ctx context.Context, t *model.Tenant) error {
	return r.sys(ctx).Create(t).Error
}

func (r *Repo) CreateUser(ctx context.Context, u *model.User) error {
	return r.sys(ctx).Create(u).Error
}

func (r *Repo) UserByEmail(ctx context.Context, email string) (*model.User, error) {
	var u model.User
	err := r.sys(ctx).Where("email = ?", email).First(&u).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &u, err
}

func (r *Repo) UserByID(ctx context.Context, id int64) (*model.User, error) {
	var u model.User
	err := r.sys(ctx).First(&u, id).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &u, err
}

func (r *Repo) TenantByID(ctx context.Context, id int64) (*model.Tenant, error) {
	var t model.Tenant
	err := r.sys(ctx).First(&t, id).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &t, err
}

func (r *Repo) ConversationByPublicSystem(ctx context.Context, publicID string) (*model.Conversation, error) {
	var c model.Conversation
	err := r.sys(ctx).Where("public_id = ? AND deleted_at IS NULL", publicID).First(&c).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &c, err
}

func (r *Repo) ConversationByIDSystem(ctx context.Context, id int64) (*model.Conversation, error) {
	var c model.Conversation
	err := r.sys(ctx).Where("id = ? AND deleted_at IS NULL", id).First(&c).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &c, err
}

func (r *Repo) ConversationByPublic(ctx context.Context, publicID string) (*model.Conversation, error) {
	var c model.Conversation
	err := r.scoped(ctx).Where("public_id = ? AND deleted_at IS NULL", publicID).First(&c).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &c, err
}

func (r *Repo) ListConversations(ctx context.Context, before *time.Time, limit int) ([]model.Conversation, error) {
	q := r.scoped(ctx).Where("deleted_at IS NULL").Order("updated_at DESC").Limit(limit)
	if before != nil {
		q = q.Where("updated_at < ?", *before)
	}
	var out []model.Conversation
	return out, q.Find(&out).Error
}

func (r *Repo) CreateConversation(ctx context.Context, c *model.Conversation) error {
	p := tenant.MustFrom(ctx)
	c.TenantID = p.TenantID
	c.UserID = p.UserID
	return r.scoped(ctx).Create(c).Error
}

func (r *Repo) UpdateConversationTitle(ctx context.Context, id int64, title string) error {
	return r.scoped(ctx).Model(&model.Conversation{}).Where("id = ?", id).Updates(map[string]any{
		"title":      title,
		"updated_at": time.Now().UTC(),
	}).Error
}

func (r *Repo) SoftDeleteConversation(ctx context.Context, id int64) error {
	now := time.Now().UTC()
	return r.scoped(ctx).Model(&model.Conversation{}).Where("id = ?", id).Updates(map[string]any{
		"deleted_at": now,
		"updated_at": now,
	}).Error
}

func (r *Repo) ClaimActiveRunSystem(ctx context.Context, convID, runID int64) (bool, error) {
	res := r.sys(ctx).Model(&model.Conversation{}).
		Where("id = ? AND active_run_id IS NULL AND deleted_at IS NULL", convID).
		Update("active_run_id", runID)
	return res.RowsAffected == 1, res.Error
}

func (r *Repo) ClaimActiveRun(ctx context.Context, convID, runID int64) (bool, error) {
	p := tenant.MustFrom(ctx)
	res := r.DB.System(ctx).Model(&model.Conversation{}).
		Where("id = ? AND tenant_id = ? AND user_id = ? AND active_run_id IS NULL AND deleted_at IS NULL", convID, p.TenantID, p.UserID).
		Update("active_run_id", runID)
	return res.RowsAffected == 1, res.Error
}

func (r *Repo) ClearActiveRun(ctx context.Context, convID, runID int64) error {
	return r.sys(ctx).Model(&model.Conversation{}).
		Where("id = ? AND active_run_id = ?", convID, runID).
		Update("active_run_id", nil).Error
}

func (r *Repo) TouchConversation(ctx context.Context, id int64) error {
	return r.sys(ctx).Model(&model.Conversation{}).Where("id = ?", id).Update("updated_at", time.Now().UTC()).Error
}

func (r *Repo) CreateRunSystem(ctx context.Context, run *model.Run) error {
	return r.sys(ctx).Create(run).Error
}

func (r *Repo) CreateRun(ctx context.Context, run *model.Run) error {
	p := tenant.MustFrom(ctx)
	run.TenantID = p.TenantID
	run.UserID = p.UserID
	return r.DB.System(ctx).Create(run).Error
}

func (r *Repo) RunByPublic(ctx context.Context, publicID string) (*model.Run, error) {
	var run model.Run
	err := r.scoped(ctx).Where("public_id = ?", publicID).First(&run).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &run, err
}

func (r *Repo) RunByPublicSystem(ctx context.Context, publicID string) (*model.Run, error) {
	var run model.Run
	err := r.sys(ctx).Where("public_id = ?", publicID).First(&run).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &run, err
}

func (r *Repo) RunByID(ctx context.Context, id int64) (*model.Run, error) {
	var run model.Run
	err := r.scoped(ctx).Where("id = ?", id).First(&run).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &run, err
}

func (r *Repo) CreateMessage(ctx context.Context, m *model.Message) error {
	p := tenant.MustFrom(ctx)
	m.TenantID = p.TenantID
	m.UserID = p.UserID
	return r.DB.System(ctx).Create(m).Error
}

func (r *Repo) ListMessages(ctx context.Context, convID int64, beforeID *int64, limit int) ([]model.Message, error) {
	q := r.scoped(ctx).Where("conversation_id = ?", convID).Order("id DESC").Limit(limit)
	if beforeID != nil {
		q = q.Where("id < ?", *beforeID)
	}
	var out []model.Message
	if err := q.Find(&out).Error; err != nil {
		return nil, err
	}
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out, nil
}

func (r *Repo) CreateAttachment(ctx context.Context, a *model.Attachment) error {
	p := tenant.MustFrom(ctx)
	a.TenantID = p.TenantID
	a.UserID = p.UserID
	return r.DB.System(ctx).Create(a).Error
}

func (r *Repo) AttachmentsByMessageIDs(ctx context.Context, ids []int64) (map[int64][]model.Attachment, error) {
	out := map[int64][]model.Attachment{}
	if len(ids) == 0 {
		return out, nil
	}
	var rows []model.Attachment
	if err := r.scoped(ctx).Where("message_id IN ?", ids).Order("id ASC").Find(&rows).Error; err != nil {
		return nil, err
	}
	for _, a := range rows {
		out[a.MessageID] = append(out[a.MessageID], a)
	}
	return out, nil
}

func (r *Repo) History(ctx context.Context, convID int64, limit int) ([]model.Message, error) {
	var out []model.Message
	err := r.sys(ctx).Where("conversation_id = ?", convID).Order("id DESC").Limit(limit).Find(&out).Error
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out, err
}

func (r *Repo) InsertEvent(ctx context.Context, ev *model.RunEvent) (bool, error) {
	err := r.sys(ctx).Create(ev).Error
	if err == nil {
		return true, nil
	}
	if isDup(err) {
		return false, nil
	}
	return false, err
}

func (r *Repo) EventsAfter(ctx context.Context, runID, after int64, limit int) ([]model.RunEvent, error) {
	q := r.scoped(ctx).Where("run_id = ? AND seq > ?", runID, after).Order("seq ASC")
	if limit > 0 {
		q = q.Limit(limit)
	}
	var out []model.RunEvent
	return out, q.Find(&out).Error
}

func (r *Repo) EventsFromSystem(ctx context.Context, runID, after int64) ([]model.RunEvent, error) {
	var out []model.RunEvent
	return out, r.sys(ctx).Where("run_id = ? AND seq > ?", runID, after).Order("seq ASC").Find(&out).Error
}

func (r *Repo) MaxSeq(ctx context.Context, runID int64) (int64, error) {
	var seq int64
	err := r.sys(ctx).Model(&model.RunEvent{}).Where("run_id = ?", runID).Select("COALESCE(MAX(seq),0)").Scan(&seq).Error
	return seq, err
}

func (r *Repo) InsertAssistant(ctx context.Context, m *model.Message) error {
	err := r.sys(ctx).Create(m).Error
	if isDup(err) {
		return nil
	}
	return err
}

func (r *Repo) SaveRun(ctx context.Context, run *model.Run) error {
	return r.sys(ctx).Save(run).Error
}

func (r *Repo) StaleRuns(ctx context.Context, queuedAfter, runningAfter time.Time) ([]model.Run, error) {
	var out []model.Run
	err := r.sys(ctx).
		Where("(status = ? AND created_at < ?) OR (status = ? AND COALESCE(last_event_at, updated_at) < ?)",
			model.RunQueued, queuedAfter, model.RunRunning, runningAfter).
		Limit(100).
		Find(&out).Error
	return out, err
}

func (r *Repo) DeleteOldEvents(ctx context.Context, before time.Time, batch int) (int64, error) {
	res := r.sys(ctx).Where("created_at < ?", before).Limit(batch).Delete(&model.RunEvent{})
	return res.RowsAffected, res.Error
}

type IdleConversation struct {
	TenantPublic       string `gorm:"column:tenant_public"`
	ConversationPublic string `gorm:"column:conversation_public"`
}

func (r *Repo) IdleConversations(ctx context.Context, cutoff time.Time, limit int) ([]IdleConversation, error) {
	if limit <= 0 {
		limit = 100
	}
	var out []IdleConversation
	err := r.sys(ctx).Table("conversations AS c").
		Select("t.public_id AS tenant_public, c.public_id AS conversation_public").
		Joins("JOIN tenants t ON t.id = c.tenant_id").
		Where("c.updated_at < ? AND c.active_run_id IS NULL", cutoff).
		Limit(limit).
		Scan(&out).Error
	return out, err
}

func isDup(err error) bool {
	if err == nil {
		return false
	}
	s := err.Error()
	return contains(s, "Duplicate") || contains(s, "1062")
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(sub) == 0 || (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})())
}

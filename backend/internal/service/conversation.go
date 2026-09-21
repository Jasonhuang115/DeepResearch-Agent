package service

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"
	"unicode/utf8"

	"deepresearch/internal/blob"
	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/httpx"
	"deepresearch/internal/id"
	"deepresearch/internal/model"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
	"deepresearch/internal/tenant"
	"deepresearch/internal/upload"
)

type Conversations struct {
	Repo     *repo.Repo
	Redis    *cache.Redis
	Producer *mq.Producer
	Cfg      config.Config
	Blob     blob.Store
}

func (s *Conversations) List(ctx context.Context, before *time.Time, limit int) (ListOut[ConversationView], error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	items, err := s.Repo.ListConversations(ctx, before, limit+1)
	if err != nil {
		return ListOut[ConversationView]{}, err
	}
	var next *string
	if len(items) > limit {
		t := items[limit-1].UpdatedAt.UTC().Format(time.RFC3339Nano)
		next = &t
		items = items[:limit]
	}
	out := make([]ConversationView, 0, len(items))
	for _, c := range items {
		var run *model.Run
		if c.ActiveRunID != nil {
			run, _ = s.Repo.RunByID(ctx, *c.ActiveRunID)
		}
		out = append(out, convView(c, run))
	}
	return ListOut[ConversationView]{Items: out, NextBefore: next}, nil
}

func (s *Conversations) Get(ctx context.Context, publicID string) (*ConversationView, error) {
	c, err := s.Repo.ConversationByPublic(ctx, publicID)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, httpx.ErrNotFound
	}
	var run *model.Run
	if c.ActiveRunID != nil {
		run, _ = s.Repo.RunByID(ctx, *c.ActiveRunID)
	}
	v := convView(*c, run)
	return &v, nil
}

type CreateConvIn struct {
	Title   string
	Content string
	Files   []upload.Incoming
}

func (s *Conversations) Create(ctx context.Context, in CreateConvIn) (map[string]any, error) {
	title := strings.TrimSpace(in.Title)
	content := strings.TrimSpace(in.Content)
	if content != "" || len(in.Files) > 0 {
		if err := validateMessage(content, len(in.Files)); err != nil {
			return nil, err
		}
	}
	if title == "" {
		if content != "" {
			title = titleFrom(content)
		} else if len(in.Files) > 0 {
			title = titleFrom(in.Files[0].Filename)
		}
	}
	if title == "" {
		title = "Untitled"
	}
	c := &model.Conversation{PublicID: id.New("conv_"), Title: title}
	if err := s.Repo.CreateConversation(ctx, c); err != nil {
		return nil, err
	}
	if content == "" && len(in.Files) == 0 {
		v := convView(*c, nil)
		return map[string]any{"conversation": v}, nil
	}
	msg, run, err := s.startRun(ctx, c, content, in.Files)
	if err != nil {
		return nil, err
	}
	cv := convView(*c, run)
	return map[string]any{
		"conversation": cv,
		"message":      msg,
		"run":          runView(*run, c.PublicID),
	}, nil
}

func (s *Conversations) PatchTitle(ctx context.Context, publicID, title string) (*ConversationView, error) {
	title = strings.TrimSpace(title)
	if title == "" {
		return nil, httpx.ErrValidation
	}
	c, err := s.Repo.ConversationByPublic(ctx, publicID)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, httpx.ErrNotFound
	}
	if err := s.Repo.UpdateConversationTitle(ctx, c.ID, title); err != nil {
		return nil, err
	}
	c.Title = title
	v := convView(*c, nil)
	return &v, nil
}

func (s *Conversations) Delete(ctx context.Context, publicID string) error {
	c, err := s.Repo.ConversationByPublic(ctx, publicID)
	if err != nil {
		return err
	}
	if c == nil {
		return httpx.ErrNotFound
	}
	if c.ActiveRunID != nil {
		if run, _ := s.Repo.RunByID(ctx, *c.ActiveRunID); run != nil && !model.Terminal(run.Status) {
			_ = s.Cancel(ctx, run.PublicID)
		}
	}
	if err := s.Repo.SoftDeleteConversation(ctx, c.ID); err != nil {
		return err
	}
	s.deleteWorkspacePrefix(ctx, c.PublicID)
	return nil
}

func (s *Conversations) deleteWorkspacePrefix(ctx context.Context, conversationPublic string) {
	if s.Blob == nil {
		return
	}
	p, err := tenant.FromContext(ctx)
	if err != nil || p.TenantPublic == "" {
		return
	}
	prefix := blob.SessionPrefix(p.TenantPublic, conversationPublic)
	if err := s.Blob.DeletePrefix(ctx, prefix); err != nil {
		slog.Warn("delete workspace prefix", "prefix", prefix, "err", err)
	}
}

func (s *Conversations) Messages(ctx context.Context, convPublic string, beforeID *int64, limit int) (ListOut[MessageView], error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	c, err := s.Repo.ConversationByPublic(ctx, convPublic)
	if err != nil {
		return ListOut[MessageView]{}, err
	}
	if c == nil {
		return ListOut[MessageView]{}, httpx.ErrNotFound
	}
	items, err := s.Repo.ListMessages(ctx, c.ID, beforeID, limit+1)
	if err != nil {
		return ListOut[MessageView]{}, err
	}
	var next *string
	if len(items) > limit {
		id := items[0].ID
		s := itoa(id)
		next = &s
		items = items[1:]
	}
	out := make([]MessageView, 0, len(items))
	ids := make([]int64, 0, len(items))
	for _, m := range items {
		ids = append(ids, m.ID)
	}
	byMsg, err := s.Repo.AttachmentsByMessageIDs(ctx, ids)
	if err != nil {
		return ListOut[MessageView]{}, err
	}
	for _, m := range items {
		var rp *string
		if m.RunID != nil {
			if run, _ := s.Repo.RunByID(ctx, *m.RunID); run != nil {
				rp = &run.PublicID
			}
		}
		out = append(out, msgView(m, c.PublicID, rp, byMsg[m.ID]))
	}
	return ListOut[MessageView]{Items: out, NextBefore: next}, nil
}

func (s *Conversations) PostMessage(ctx context.Context, convPublic, content string, files []upload.Incoming) (MessageView, RunView, error) {
	content = strings.TrimSpace(content)
	if err := validateMessage(content, len(files)); err != nil {
		return MessageView{}, RunView{}, err
	}
	c, err := s.Repo.ConversationByPublic(ctx, convPublic)
	if err != nil {
		return MessageView{}, RunView{}, err
	}
	if c == nil {
		return MessageView{}, RunView{}, httpx.ErrNotFound
	}
	mv, run, err := s.startRun(ctx, c, content, files)
	if err != nil {
		return MessageView{}, RunView{}, err
	}
	return mv, runView(*run, c.PublicID), nil
}

func (s *Conversations) startRun(ctx context.Context, c *model.Conversation, content string, files []upload.Incoming) (MessageView, *model.Run, error) {
	if err := s.checkFiles(files); err != nil {
		return MessageView{}, nil, err
	}
	p := tenant.MustFrom(ctx)
	run := &model.Run{
		PublicID:       id.New("run_"),
		TenantID:       p.TenantID,
		UserID:         p.UserID,
		ConversationID: c.ID,
		Status:         model.RunQueued,
	}
	if err := s.Repo.CreateRun(ctx, run); err != nil {
		return MessageView{}, nil, err
	}
	ok, err := s.Repo.ClaimActiveRun(ctx, c.ID, run.ID)
	if err != nil {
		return MessageView{}, nil, err
	}
	if !ok {
		return MessageView{}, nil, httpx.Err(409, "conflict", "a run is already active")
	}
	c.ActiveRunID = &run.ID
	um := &model.Message{
		PublicID:       id.New("msg_"),
		TenantID:       p.TenantID,
		UserID:         p.UserID,
		ConversationID: c.ID,
		RunID:          &run.ID,
		Role:           "user",
		Content:        content,
	}
	if err := s.Repo.CreateMessage(ctx, um); err != nil {
		return MessageView{}, nil, err
	}
	saved, err := s.saveAttachments(ctx, c.ID, um.ID, files)
	if err != nil {
		return MessageView{}, nil, err
	}
	_ = s.Repo.TouchConversation(ctx, c.ID)

	hist, _ := s.Repo.History(ctx, c.ID, s.Cfg.HistoryMessageLimit)
	msgs := make([]mq.Msg, 0, len(hist))
	chars := 0
	for _, m := range hist {
		chars += utf8.RuneCountInString(m.Content)
		if chars > s.Cfg.HistoryCharLimit {
			break
		}
		msgs = append(msgs, mq.Msg{ID: m.PublicID, Role: m.Role, Content: m.Content})
	}
	refs := make([]mq.AttachmentRef, 0, len(saved))
	for _, a := range saved {
		abs, err := upload.Abs(s.Cfg.UploadDir, a.StoragePath)
		if err != nil {
			return MessageView{}, nil, err
		}
		refs = append(refs, mq.AttachmentRef{
			ID: a.PublicID, Filename: a.Filename, ContentType: a.ContentType,
			Path: abs, Size: a.SizeBytes,
		})
	}
	cmd := mq.Command{
		V: 1, Type: "start",
		RunID: run.PublicID, ConversationID: c.PublicID,
		TenantID: p.TenantPublic, UserID: p.UserPublic,
		Request:  &mq.Request{Content: content, Attachments: refs},
		Messages: msgs, CreatedAt: time.Now().UTC(),
	}
	if err := s.Producer.Write(ctx, s.Cfg.CommandsTopic, c.PublicID, cmd); err != nil {
		// sweeper will fail the queued run
	}
	rp := run.PublicID
	return msgView(*um, c.PublicID, &rp, saved), run, nil
}

func (s *Conversations) checkFiles(files []upload.Incoming) error {
	if len(files) > s.Cfg.UploadMaxFiles {
		return httpx.Err(400, "validation", "too many files")
	}
	for _, f := range files {
		if int64(len(f.Data)) > s.Cfg.UploadMaxBytes {
			return httpx.Err(400, "validation", "file is too large")
		}
	}
	return nil
}

func (s *Conversations) saveAttachments(ctx context.Context, convID, messageID int64, files []upload.Incoming) ([]model.Attachment, error) {
	out := make([]model.Attachment, 0, len(files))
	for _, f := range files {
		publicID := id.New("att_")
		rel, err := upload.Write(s.Cfg.UploadDir, publicID, f.Data)
		if err != nil {
			return nil, err
		}
		row := &model.Attachment{
			PublicID:       publicID,
			ConversationID: convID,
			MessageID:      messageID,
			Filename:       f.Filename,
			ContentType:    f.ContentType,
			SizeBytes:      int64(len(f.Data)),
			SHA256:         upload.SHA256(f.Data),
			StoragePath:    rel,
		}
		if err := s.Repo.CreateAttachment(ctx, row); err != nil {
			return nil, err
		}
		out = append(out, *row)
	}
	return out, nil
}

func (s *Conversations) GetRun(ctx context.Context, publicID string) (*RunView, error) {
	run, err := s.Repo.RunByPublic(ctx, publicID)
	if err != nil {
		return nil, err
	}
	if run == nil {
		return nil, httpx.ErrNotFound
	}
	var conv model.Conversation
	if err := s.Repo.DB.Scoped(ctx).Where("id = ?", run.ConversationID).First(&conv).Error; err != nil {
		return nil, httpx.ErrNotFound
	}
	v := runView(*run, conv.PublicID)
	return &v, nil
}

func (s *Conversations) Cancel(ctx context.Context, runPublic string) error {
	run, err := s.Repo.RunByPublic(ctx, runPublic)
	if err != nil {
		return err
	}
	if run == nil {
		return httpx.ErrNotFound
	}
	if model.Terminal(run.Status) {
		return nil
	}
	var conv model.Conversation
	if err := s.Repo.DB.Scoped(ctx).Where("id = ?", run.ConversationID).First(&conv).Error; err != nil {
		return httpx.ErrNotFound
	}
	p := tenant.MustFrom(ctx)
	cmd := mq.Command{
		V: 1, Type: "cancel",
		RunID: run.PublicID, ConversationID: conv.PublicID,
		TenantID: p.TenantPublic, Reason: "user_requested",
		CreatedAt: time.Now().UTC(),
	}
	return s.Producer.Write(ctx, s.Cfg.CommandsTopic, conv.PublicID, cmd)
}

func (s *Conversations) Events(ctx context.Context, runPublic string, after int64, limit int) ([]map[string]any, error) {
	run, err := s.Repo.RunByPublic(ctx, runPublic)
	if err != nil {
		return nil, err
	}
	if run == nil {
		return nil, httpx.ErrNotFound
	}
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	rows, err := s.Repo.EventsAfter(ctx, run.ID, after, limit)
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(rows))
	for _, e := range rows {
		var payload any
		_ = json.Unmarshal(e.Payload, &payload)
		out = append(out, map[string]any{
			"seq": e.Seq, "type": e.Type, "payload": payload, "ts": e.CreatedAt.UTC().Format(time.RFC3339Nano),
		})
	}
	return out, nil
}

func validateMessage(content string, nFiles int) error {
	n := utf8.RuneCountInString(content)
	if n > 32000 {
		return httpx.Err(400, "validation", "content must be at most 32000 characters")
	}
	if n < 1 && nFiles == 0 {
		return httpx.Err(400, "validation", "content or at least one file is required")
	}
	return nil
}

func validateContent(s string) error {
	return validateMessage(strings.TrimSpace(s), 0)
}

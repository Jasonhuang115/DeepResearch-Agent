package service

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"sync"
	"time"
	"unicode/utf8"

	"deepresearch/internal/config"
	"deepresearch/internal/id"
	"deepresearch/internal/model"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
)

var errWakeBusy = errors.New("conversation has an active run")

type wakeBatch struct {
	TenantID string
	UserID   string
	Reports  []mq.WakeReport
}

type wakeQueue struct {
	mu      sync.Mutex
	pending map[string]*wakeBatch
}

func newWakeQueue() *wakeQueue {
	return &wakeQueue{pending: map[string]*wakeBatch{}}
}

func (q *wakeQueue) add(conversationID, tenantID, userID string, report mq.WakeReport) {
	q.mu.Lock()
	defer q.mu.Unlock()
	batch := q.pending[conversationID]
	if batch == nil {
		batch = &wakeBatch{TenantID: tenantID, UserID: userID}
		q.pending[conversationID] = batch
	}
	for i, existing := range batch.Reports {
		if existing.ID == report.ID {
			batch.Reports[i] = report
			return
		}
	}
	batch.Reports = append(batch.Reports, report)
}

func (q *wakeQueue) take(conversationID string) *wakeBatch {
	q.mu.Lock()
	defer q.mu.Unlock()
	batch := q.pending[conversationID]
	delete(q.pending, conversationID)
	if batch == nil || len(batch.Reports) == 0 {
		return nil
	}
	return batch
}

func (q *wakeQueue) restore(conversationID string, batch *wakeBatch) {
	if batch == nil || len(batch.Reports) == 0 {
		return
	}
	q.mu.Lock()
	defer q.mu.Unlock()
	current := q.pending[conversationID]
	if current == nil {
		q.pending[conversationID] = batch
		return
	}
	seen := map[string]bool{}
	for _, report := range current.Reports {
		seen[report.ID] = true
	}
	merged := append([]mq.WakeReport{}, batch.Reports...)
	for _, report := range current.Reports {
		if seen[report.ID] && containsReport(batch.Reports, report.ID) {
			continue
		}
		merged = append(merged, report)
	}
	current.Reports = merged
}

func containsReport(reports []mq.WakeReport, id string) bool {
	for _, report := range reports {
		if report.ID == id {
			return true
		}
	}
	return false
}

func (q *wakeQueue) drop(conversationID string) {
	q.mu.Lock()
	defer q.mu.Unlock()
	delete(q.pending, conversationID)
}

type SubagentWakes struct {
	Repo     *repo.Repo
	Producer *mq.Producer
	Cfg      config.Config
	queue    *wakeQueue
}

func NewSubagentWakes(r *repo.Repo, producer *mq.Producer, cfg config.Config) *SubagentWakes {
	return &SubagentWakes{Repo: r, Producer: producer, Cfg: cfg, queue: newWakeQueue()}
}

func (s *SubagentWakes) Handle(ctx context.Context, raw []byte) error {
	var msg mq.SubagentWake
	if err := json.Unmarshal(raw, &msg); err != nil {
		return err
	}
	if msg.ConversationID == "" || msg.TenantID == "" || msg.UserID == "" || msg.ID == "" || msg.ReportPath == "" {
		return nil
	}
	conv, err := s.Repo.ConversationByPublicSystem(ctx, msg.ConversationID)
	if err != nil || conv == nil {
		return err
	}
	tenant, err := s.Repo.TenantByID(ctx, conv.TenantID)
	if err != nil || tenant == nil || tenant.PublicID != msg.TenantID {
		return err
	}
	user, err := s.Repo.UserByID(ctx, conv.UserID)
	if err != nil || user == nil || user.PublicID != msg.UserID {
		return err
	}
	s.queue.add(msg.ConversationID, msg.TenantID, msg.UserID, mq.WakeReport{
		ID: msg.ID, Status: msg.Status, ReportPath: msg.ReportPath,
	})
	if err := s.tryStart(ctx, msg.ConversationID); err != nil {
		slog.Warn("subagent wake", "conversation", msg.ConversationID, "err", err)
	}
	return nil
}

func (s *SubagentWakes) OnRunCleared(ctx context.Context, conversationID int64) {
	conv, err := s.Repo.ConversationByIDSystem(ctx, conversationID)
	if err != nil || conv == nil {
		return
	}
	if err := s.tryStart(ctx, conv.PublicID); err != nil {
		slog.Warn("subagent wake after run", "conversation", conv.PublicID, "err", err)
	}
}

func (s *SubagentWakes) tryStart(ctx context.Context, conversationID string) error {
	conv, err := s.Repo.ConversationByPublicSystem(ctx, conversationID)
	if err != nil {
		return err
	}
	if conv == nil {
		s.queue.drop(conversationID)
		return nil
	}
	if conv.ActiveRunID != nil {
		return nil
	}
	batch := s.queue.take(conversationID)
	if batch == nil {
		return nil
	}
	if err := s.launch(ctx, conv, batch); err != nil {
		s.queue.restore(conversationID, batch)
		return err
	}
	return nil
}

func (s *SubagentWakes) launch(ctx context.Context, conv *model.Conversation, batch *wakeBatch) error {
	tenant, err := s.Repo.TenantByID(ctx, conv.TenantID)
	if err != nil {
		return err
	}
	if tenant == nil || tenant.PublicID != batch.TenantID {
		return errors.New("wake tenant does not match conversation")
	}
	user, err := s.Repo.UserByID(ctx, conv.UserID)
	if err != nil {
		return err
	}
	if user == nil || user.PublicID != batch.UserID {
		return errors.New("wake user does not match conversation")
	}
	run := &model.Run{
		PublicID:       id.New("run_"),
		TenantID:       conv.TenantID,
		UserID:         conv.UserID,
		ConversationID: conv.ID,
		Status:         model.RunQueued,
	}
	if err := s.Repo.CreateRunSystem(ctx, run); err != nil {
		return err
	}
	ok, err := s.Repo.ClaimActiveRunSystem(ctx, conv.ID, run.ID)
	if err != nil {
		return err
	}
	if !ok {
		return errWakeBusy
	}
	hist, _ := s.Repo.History(ctx, conv.ID, s.Cfg.HistoryMessageLimit)
	cmd := BuildWakeCommand(conv, batch.TenantID, batch.UserID, run.PublicID, hist, batch.Reports, s.Cfg.HistoryCharLimit)
	if err := s.Producer.Write(ctx, s.Cfg.CommandsTopic, conv.PublicID, cmd); err != nil {
		return err
	}
	return nil
}

func BuildWakeCommand(
	conv *model.Conversation,
	tenantPublic, userPublic, runPublic string,
	history []model.Message,
	reports []mq.WakeReport,
	charLimit int,
) mq.Command {
	msgs := make([]mq.Msg, 0, len(history))
	chars := 0
	for _, m := range history {
		chars += utf8.RuneCountInString(m.Content)
		if charLimit > 0 && chars > charLimit {
			break
		}
		msgs = append(msgs, mq.Msg{ID: m.PublicID, Role: m.Role, Content: m.Content})
	}
	copied := append([]mq.WakeReport{}, reports...)
	return mq.Command{
		V: 1, Type: "start",
		RunID: runPublic, ConversationID: conv.PublicID,
		TenantID: tenantPublic, UserID: userPublic,
		Request:   &mq.Request{Content: ""},
		Wake:      &mq.Wake{Reports: copied},
		Messages:  msgs,
		CreatedAt: time.Now().UTC(),
	}
}

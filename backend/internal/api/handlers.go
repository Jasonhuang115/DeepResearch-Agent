package api

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"deepresearch/internal/cache"
	"deepresearch/internal/httpx"
	"deepresearch/internal/model"
	"deepresearch/internal/service"
	"deepresearch/internal/sse"
	"deepresearch/internal/tenant"
	"deepresearch/internal/upload"
)

type Handlers struct {
	Auth  *service.Auth
	Conv  *service.Conversations
	Redis *cache.Redis
	Hub   *sse.Hub
}

type authIn struct {
	Email       string `json:"email"`
	Password    string `json:"password"`
	DisplayName string `json:"display_name"`
	Refresh     string `json:"refresh_token"`
}

func (h *Handlers) Register(c *gin.Context) {
	var in authIn
	if err := c.ShouldBindJSON(&in); err != nil {
		httpx.Fail(c, httpx.ErrValidation)
		return
	}
	out, err := h.Auth.Register(c.Request.Context(), in.Email, in.Password, in.DisplayName)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) Login(c *gin.Context) {
	var in authIn
	if err := c.ShouldBindJSON(&in); err != nil {
		httpx.Fail(c, httpx.ErrValidation)
		return
	}
	out, err := h.Auth.Login(c.Request.Context(), in.Email, in.Password)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) Refresh(c *gin.Context) {
	var in authIn
	if err := c.ShouldBindJSON(&in); err != nil {
		httpx.Fail(c, httpx.ErrValidation)
		return
	}
	out, err := h.Auth.Refresh(c.Request.Context(), in.Refresh)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) Logout(c *gin.Context) {
	var in authIn
	_ = c.ShouldBindJSON(&in)
	h.Auth.Logout(c.Request.Context(), in.Refresh)
	httpx.OK(c, map[string]any{})
}

func (h *Handlers) Me(c *gin.Context) {
	p := tenant.MustFrom(c.Request.Context())
	u, err := h.Auth.Repo.UserByID(c.Request.Context(), p.UserID)
	if err != nil || u == nil {
		httpx.Fail(c, httpx.ErrUnauthorized)
		return
	}
	ten, err := h.Auth.Repo.TenantByID(c.Request.Context(), p.TenantID)
	if err != nil || ten == nil {
		httpx.Fail(c, httpx.ErrUnauthorized)
		return
	}
	httpx.OK(c, service.UserView{
		ID: u.PublicID, Email: u.Email, DisplayName: u.DisplayName, TenantID: ten.PublicID,
	})
}

func (h *Handlers) ListConversations(c *gin.Context) {
	var before *time.Time
	if s := c.Query("before"); s != "" {
		t, err := time.Parse(time.RFC3339Nano, s)
		if err != nil {
			httpx.Fail(c, httpx.ErrValidation)
			return
		}
		before = &t
	}
	limit, _ := strconv.Atoi(c.Query("limit"))
	out, err := h.Conv.List(c.Request.Context(), before, limit)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) CreateConversation(c *gin.Context) {
	if cached, ok := h.idempotentGet(c); ok {
		c.Data(http.StatusOK, "application/json", cached)
		return
	}
	in, err := h.parseCreateIn(c)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	out, err := h.Conv.Create(c.Request.Context(), in)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	h.idempotentSave(c, out)
	httpx.OK(c, out)
}

func (h *Handlers) GetConversation(c *gin.Context) {
	out, err := h.Conv.Get(c.Request.Context(), c.Param("id"))
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) PatchConversation(c *gin.Context) {
	var in struct {
		Title string `json:"title"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		httpx.Fail(c, httpx.ErrValidation)
		return
	}
	out, err := h.Conv.PatchTitle(c.Request.Context(), c.Param("id"), in.Title)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) DeleteConversation(c *gin.Context) {
	if err := h.Conv.Delete(c.Request.Context(), c.Param("id")); err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, map[string]any{})
}

func (h *Handlers) ListMessages(c *gin.Context) {
	var before *int64
	if s := c.Query("before"); s != "" {
		n, err := strconv.ParseInt(s, 10, 64)
		if err != nil {
			httpx.Fail(c, httpx.ErrValidation)
			return
		}
		before = &n
	}
	limit, _ := strconv.Atoi(c.Query("limit"))
	out, err := h.Conv.Messages(c.Request.Context(), c.Param("id"), before, limit)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) ListSubagents(c *gin.Context) {
	out, err := h.Conv.Subagents(c.Request.Context(), c.Param("id"))
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) PostMessage(c *gin.Context) {
	if cached, ok := h.idempotentGet(c); ok {
		c.Data(http.StatusOK, "application/json", cached)
		return
	}
	content, files, err := h.parseMessageIn(c)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	msg, run, err := h.Conv.PostMessage(c.Request.Context(), c.Param("id"), content, files)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	out := map[string]any{"message": msg, "run": run}
	h.idempotentSave(c, out)
	httpx.OK(c, out)
}

func (h *Handlers) GetRun(c *gin.Context) {
	out, err := h.Conv.GetRun(c.Request.Context(), c.Param("id"))
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, out)
}

func (h *Handlers) CancelRun(c *gin.Context) {
	if err := h.Conv.Cancel(c.Request.Context(), c.Param("id")); err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.Accepted(c, map[string]any{"status": "cancelling"})
}

func (h *Handlers) ListEvents(c *gin.Context) {
	after, _ := strconv.ParseInt(c.Query("after"), 10, 64)
	limit, _ := strconv.Atoi(c.Query("limit"))
	out, err := h.Conv.Events(c.Request.Context(), c.Param("id"), after, limit)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	httpx.OK(c, map[string]any{"items": out})
}

func (h *Handlers) StreamRun(c *gin.Context) {
	run, err := h.Conv.Repo.RunByPublic(c.Request.Context(), c.Param("id"))
	if err != nil || run == nil {
		httpx.Fail(c, httpx.ErrNotFound)
		return
	}
	ch, cancel, ok := h.Hub.SubscribeRun(run.PublicID)
	if !ok {
		httpx.Fail(c, httpx.Err(http.StatusTooManyRequests, "rate_limited", "too many streams"))
		return
	}
	defer cancel()

	after := int64(0)
	if s := c.GetHeader("Last-Event-ID"); s != "" {
		after, _ = strconv.ParseInt(s, 10, 64)
	}
	replay, err := h.Conv.Repo.EventsAfter(c.Request.Context(), run.ID, after, 0)
	if err != nil {
		httpx.Fail(c, err)
		return
	}
	writeSSEHeaders(c)
	flusher, _ := c.Writer.(http.Flusher)
	maxSeq := after
	for _, e := range replay {
		payload := json.RawMessage(e.Payload)
		writeSSE(c, e.Seq, e.Type, map[string]any{
			"v": 1, "run_id": run.PublicID, "seq": e.Seq, "type": e.Type, "payload": payload,
		})
		if e.Seq > maxSeq {
			maxSeq = e.Seq
		}
	}
	if refreshed, err := h.Conv.Repo.RunByPublic(c.Request.Context(), run.PublicID); err == nil && refreshed != nil {
		run = refreshed
	}
	if model.Terminal(run.Status) {
		return
	}
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-c.Request.Context().Done():
			return
		case <-ping.C:
			_, _ = io.WriteString(c.Writer, ": ping\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		case ev, ok := <-ch:
			if !ok {
				return
			}
			if ev.Seq <= maxSeq {
				continue
			}
			maxSeq = ev.Seq
			writeSSE(c, ev.Seq, ev.Type, ev)
			if ev.Type == "run.finished" {
				return
			}
		}
	}
}

func (h *Handlers) StreamConversation(c *gin.Context) {
	conv, err := h.Conv.Repo.ConversationByPublic(c.Request.Context(), c.Param("id"))
	if err != nil || conv == nil {
		httpx.Fail(c, httpx.ErrNotFound)
		return
	}
	ch, cancel, ok := h.Hub.SubscribeConv(conv.PublicID)
	if !ok {
		httpx.Fail(c, httpx.Err(http.StatusTooManyRequests, "rate_limited", "too many streams"))
		return
	}
	defer cancel()
	writeSSEHeaders(c)
	flusher, _ := c.Writer.(http.Flusher)
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-c.Request.Context().Done():
			return
		case <-ping.C:
			_, _ = io.WriteString(c.Writer, ": ping\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		case ev, ok := <-ch:
			if !ok {
				return
			}
			writeSSE(c, ev.Seq, ev.Type, ev)
		}
	}
}

func writeSSEHeaders(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)
	c.Writer.WriteHeaderNow()
}

func writeSSE(c *gin.Context, id int64, event string, data any) {
	b, _ := json.Marshal(data)
	_, _ = io.WriteString(c.Writer, "id: "+strconv.FormatInt(id, 10)+"\n")
	_, _ = io.WriteString(c.Writer, "event: "+event+"\n")
	_, _ = io.WriteString(c.Writer, "data: "+string(b)+"\n\n")
	if f, ok := c.Writer.(http.Flusher); ok {
		f.Flush()
	}
}

func (h *Handlers) parseCreateIn(c *gin.Context) (service.CreateConvIn, error) {
	if strings.HasPrefix(c.ContentType(), "multipart/form-data") {
		files, err := h.readFiles(c)
		if err != nil {
			return service.CreateConvIn{}, err
		}
		return service.CreateConvIn{
			Title:   c.PostForm("title"),
			Content: c.PostForm("content"),
			Files:   files,
		}, nil
	}
	var in struct {
		Title   string `json:"title"`
		Content string `json:"content"`
	}
	_ = c.ShouldBindJSON(&in)
	return service.CreateConvIn{Title: in.Title, Content: in.Content}, nil
}

func (h *Handlers) parseMessageIn(c *gin.Context) (string, []upload.Incoming, error) {
	if strings.HasPrefix(c.ContentType(), "multipart/form-data") {
		files, err := h.readFiles(c)
		if err != nil {
			return "", nil, err
		}
		return c.PostForm("content"), files, nil
	}
	var in struct {
		Content string `json:"content"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		return "", nil, httpx.ErrValidation
	}
	return in.Content, nil, nil
}

func (h *Handlers) readFiles(c *gin.Context) ([]upload.Incoming, error) {
	maxMem := h.Conv.Cfg.UploadMaxBytes * int64(h.Conv.Cfg.UploadMaxFiles+1)
	if maxMem < 32<<20 {
		maxMem = 32 << 20
	}
	if err := c.Request.ParseMultipartForm(maxMem); err != nil {
		return nil, httpx.Err(http.StatusBadRequest, "validation", "invalid multipart body")
	}
	form := c.Request.MultipartForm
	if form == nil {
		return nil, nil
	}
	headers := form.File["files"]
	if len(headers) == 0 {
		headers = form.File["file"]
	}
	if len(headers) > h.Conv.Cfg.UploadMaxFiles {
		return nil, httpx.Err(http.StatusBadRequest, "validation", "too many files")
	}
	out := make([]upload.Incoming, 0, len(headers))
	for _, fh := range headers {
		if fh.Size > h.Conv.Cfg.UploadMaxBytes {
			return nil, httpx.Err(http.StatusBadRequest, "validation", "file is too large")
		}
		f, err := fh.Open()
		if err != nil {
			return nil, httpx.ErrValidation
		}
		data, err := io.ReadAll(io.LimitReader(f, h.Conv.Cfg.UploadMaxBytes+1))
		_ = f.Close()
		if err != nil {
			return nil, httpx.ErrValidation
		}
		if int64(len(data)) > h.Conv.Cfg.UploadMaxBytes {
			return nil, httpx.Err(http.StatusBadRequest, "validation", "file is too large")
		}
		item, err := upload.Classify(fh.Filename, data)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, nil
}

func (h *Handlers) idempotentGet(c *gin.Context) ([]byte, bool) {
	key := strings.TrimSpace(c.GetHeader("Idempotency-Key"))
	if key == "" {
		return nil, false
	}
	p := tenant.MustFrom(c.Request.Context())
	var raw []byte
	ok, err := h.Redis.GetJSON(c.Request.Context(), "idemp:"+p.TenantPublic+":"+key, &raw)
	if err != nil || !ok {
		return nil, false
	}
	return raw, true
}

func (h *Handlers) idempotentSave(c *gin.Context, data any) {
	key := strings.TrimSpace(c.GetHeader("Idempotency-Key"))
	if key == "" {
		return
	}
	p := tenant.MustFrom(c.Request.Context())
	env := httpx.Envelope{Data: data}
	b, _ := json.Marshal(env)
	_ = h.Redis.SetJSON(c.Request.Context(), "idemp:"+p.TenantPublic+":"+key, b, 24*time.Hour)
}

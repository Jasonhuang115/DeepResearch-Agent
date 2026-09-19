package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/db"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
	"deepresearch/internal/service"
	"deepresearch/internal/sse"
)

func TestCrossUserConversationIs404(t *testing.T) {
	dsn := os.Getenv("MYSQL_DSN")
	if dsn == "" {
		t.Skip("MYSQL_DSN not set")
	}
	cfg, _ := config.Load()
	cfg.MySQLDSN = dsn
	d, err := db.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := d.Migrate(); err != nil {
		t.Fatal(err)
	}
	rdb := cache.Open(cfg.RedisAddr)
	prod := mq.NewProducer(cfg.KafkaBrokers)
	r := repo.New(d)
	auth := &service.Auth{Repo: r, Redis: rdb, Cfg: cfg}
	conv := &service.Conversations{Repo: r, Redis: rdb, Producer: prod, Cfg: cfg}
	engine := Router(Deps{Cfg: cfg, Auth: auth, Conv: conv, Redis: rdb, Hub: sse.New()})

	tokA := register(t, engine, "a@example.com", "password1", "Ada")
	tokB := register(t, engine, "b@example.com", "password1", "Bob")
	convID := createConv(t, engine, tokA)

	req := httptest.NewRequest(http.MethodGet, "/v1/conversations/"+convID, nil)
	req.Header.Set("Authorization", "Bearer "+tokB)
	w := httptest.NewRecorder()
	engine.ServeHTTP(w, req)
	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d %s", w.Code, w.Body.String())
	}
}

func register(t *testing.T, h http.Handler, email, pass, name string) string {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"email": email, "password": pass, "display_name": name})
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("register %s: %d %s", email, w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			AccessToken string `json:"access_token"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	return env.Data.AccessToken
}

func createConv(t *testing.T, h http.Handler, token string) string {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/v1/conversations", bytes.NewReader([]byte(`{}`)))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("create conv: %d %s", w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			Conversation struct {
				ID string `json:"id"`
			} `json:"conversation"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	return env.Data.Conversation.ID
}

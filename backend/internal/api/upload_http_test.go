package api

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"deepresearch/internal/cache"
	"deepresearch/internal/config"
	"deepresearch/internal/db"
	"deepresearch/internal/mq"
	"deepresearch/internal/repo"
	"deepresearch/internal/service"
	"deepresearch/internal/sse"
)

func TestUploadMultipartAndRejects(t *testing.T) {
	dsn := os.Getenv("MYSQL_DSN")
	if dsn == "" {
		t.Skip("MYSQL_DSN not set")
	}
	cfg, _ := config.Load()
	cfg.MySQLDSN = dsn
	cfg.UploadDir = t.TempDir()
	cfg.UploadMaxFiles = 5
	cfg.UploadMaxBytes = 1024
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

	tok := register(t, engine, uniqueEmail("up"), "password1", "Uploader")
	convID := createConv(t, engine, tok)

	t.Run("json still works", func(t *testing.T) {
		body, _ := json.Marshal(map[string]string{"content": "plain question"})
		req := httptest.NewRequest(http.MethodPost, "/v1/conversations/"+convID+"/messages", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+tok)
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		engine.ServeHTTP(w, req)
		if w.Code != 200 && w.Code != 409 {
			t.Fatalf("json post: %d %s", w.Code, w.Body.String())
		}
	})

	convID2 := createConv(t, engine, tok)

	t.Run("txt attachment only", func(t *testing.T) {
		var buf bytes.Buffer
		mw := multipart.NewWriter(&buf)
		fw, _ := mw.CreateFormFile("files", "notes.txt")
		_, _ = fw.Write([]byte("hello from notes"))
		_ = mw.Close()
		req := httptest.NewRequest(http.MethodPost, "/v1/conversations/"+convID2+"/messages", &buf)
		req.Header.Set("Authorization", "Bearer "+tok)
		req.Header.Set("Content-Type", mw.FormDataContentType())
		w := httptest.NewRecorder()
		engine.ServeHTTP(w, req)
		if w.Code != 200 {
			t.Fatalf("multipart: %d %s", w.Code, w.Body.String())
		}
		if !strings.Contains(w.Body.String(), "notes.txt") {
			t.Fatalf("expected filename in response: %s", w.Body.String())
		}
		ents, _ := os.ReadDir(cfg.UploadDir)
		if len(ents) == 0 {
			t.Fatal("expected file on disk")
		}
	})

	t.Run("rejects exe", func(t *testing.T) {
		convID3 := createConv(t, engine, tok)
		var buf bytes.Buffer
		mw := multipart.NewWriter(&buf)
		fw, _ := mw.CreateFormFile("files", "bad.exe")
		_, _ = fw.Write([]byte("MZ"))
		_ = mw.Close()
		req := httptest.NewRequest(http.MethodPost, "/v1/conversations/"+convID3+"/messages", &buf)
		req.Header.Set("Authorization", "Bearer "+tok)
		req.Header.Set("Content-Type", mw.FormDataContentType())
		w := httptest.NewRecorder()
		engine.ServeHTTP(w, req)
		if w.Code != 400 {
			t.Fatalf("expected 400, got %d %s", w.Code, w.Body.String())
		}
	})

	t.Run("rejects oversized", func(t *testing.T) {
		convID4 := createConv(t, engine, tok)
		var buf bytes.Buffer
		mw := multipart.NewWriter(&buf)
		fw, _ := mw.CreateFormFile("files", "big.txt")
		_, _ = fw.Write(bytes.Repeat([]byte("a"), 2048))
		_ = mw.Close()
		req := httptest.NewRequest(http.MethodPost, "/v1/conversations/"+convID4+"/messages", &buf)
		req.Header.Set("Authorization", "Bearer "+tok)
		req.Header.Set("Content-Type", mw.FormDataContentType())
		w := httptest.NewRecorder()
		engine.ServeHTTP(w, req)
		if w.Code != 400 {
			t.Fatalf("expected 400, got %d %s", w.Code, w.Body.String())
		}
	})
}

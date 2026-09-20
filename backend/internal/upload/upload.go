package upload

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"deepresearch/internal/httpx"
)

const (
	ExtPDF  = ".pdf"
	ExtDOCX = ".docx"
	ExtTXT  = ".txt"
	ExtMD   = ".md"
	ExtCSV  = ".csv"
)

var allowed = map[string]string{
	ExtPDF:  "application/pdf",
	ExtDOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	ExtTXT:  "text/plain",
	ExtMD:   "text/markdown",
	ExtCSV:  "text/csv",
}

type Incoming struct {
	Filename    string
	ContentType string
	Data        []byte
}

func ResolveDir(raw string) string {
	if strings.TrimSpace(raw) == "" {
		raw = "data/uploads"
	}
	if filepath.IsAbs(raw) {
		return raw
	}
	cwd, err := os.Getwd()
	if err != nil {
		return raw
	}
	if raw == "data/uploads" {
		if _, err := os.Stat(filepath.Join(cwd, "go.mod")); err == nil {
			return filepath.Clean(filepath.Join(cwd, "..", "data", "uploads"))
		}
	}
	return filepath.Clean(filepath.Join(cwd, raw))
}

func Classify(filename string, data []byte) (Incoming, error) {
	name := filepath.Base(strings.ReplaceAll(filename, "\\", "/"))
	name = strings.TrimSpace(name)
	if name == "" || name == "." || name == ".." {
		return Incoming{}, httpx.Err(400, "validation", "filename is required")
	}
	if len(data) == 0 {
		return Incoming{}, httpx.Err(400, "validation", "file is empty")
	}
	ext := strings.ToLower(filepath.Ext(name))
	ctype, ok := allowed[ext]
	if !ok {
		return Incoming{}, httpx.Err(400, "validation", "unsupported file type")
	}
	if err := checkMagic(ext, data); err != nil {
		return Incoming{}, err
	}
	return Incoming{Filename: name, ContentType: ctype, Data: data}, nil
}

func checkMagic(ext string, data []byte) error {
	switch ext {
	case ExtPDF:
		head := data
		if len(head) > 1024 {
			head = head[:1024]
		}
		if !bytes.Contains(head, []byte("%PDF")) {
			return httpx.Err(400, "validation", "file is not a valid PDF")
		}
	case ExtDOCX:
		if !bytes.HasPrefix(data, []byte("PK")) {
			return httpx.Err(400, "validation", "file is not a valid DOCX")
		}
	case ExtTXT, ExtMD, ExtCSV:
		if bytes.IndexByte(data[:min(len(data), 512)], 0) >= 0 {
			return httpx.Err(400, "validation", "text file contains binary data")
		}
		if !utf8.Valid(data) {
			return httpx.Err(400, "validation", "text file is not valid UTF-8")
		}
	}
	return nil
}

func SHA256(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func Write(root, publicID string, data []byte) (string, error) {
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", err
	}
	rel := publicID
	abs := filepath.Join(root, rel)
	if err := os.WriteFile(abs, data, 0o644); err != nil {
		return "", err
	}
	return rel, nil
}

func Abs(root, rel string) (string, error) {
	clean := filepath.Clean("/" + strings.ReplaceAll(rel, "\\", "/"))
	clean = strings.TrimPrefix(clean, "/")
	if clean == "" || strings.Contains(clean, "..") {
		return "", fmt.Errorf("invalid storage path")
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	full := filepath.Join(rootAbs, filepath.FromSlash(clean))
	fullAbs, err := filepath.Abs(full)
	if err != nil {
		return "", err
	}
	sep := string(filepath.Separator)
	if fullAbs != rootAbs && !strings.HasPrefix(fullAbs, rootAbs+sep) {
		return "", fmt.Errorf("path escapes upload dir")
	}
	return fullAbs, nil
}

package blob

import (
	"context"
	"os"
	"path/filepath"
	"strings"
)

type Local struct {
	Root string
}

func NewLocal(root string) *Local {
	return &Local{Root: root}
}

func (s *Local) path(key string) (string, error) {
	rel := strings.TrimPrefix(filepath.ToSlash(key), "/")
	if rel == "" || strings.HasSuffix(rel, "/") {
		return "", os.ErrInvalid
	}
	for _, p := range strings.Split(rel, "/") {
		if p == ".." {
			return "", os.ErrInvalid
		}
	}
	root, err := filepath.Abs(s.Root)
	if err != nil {
		return "", err
	}
	target := filepath.Join(root, filepath.FromSlash(rel))
	abs, err := filepath.Abs(target)
	if err != nil {
		return "", err
	}
	if abs != root && !strings.HasPrefix(abs, root+string(os.PathSeparator)) {
		return "", os.ErrInvalid
	}
	return abs, nil
}

func (s *Local) Put(_ context.Context, key string, data []byte) error {
	path, err := s.path(key)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func (s *Local) Get(_ context.Context, key string) ([]byte, error) {
	path, err := s.path(key)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}

func (s *Local) List(_ context.Context, prefix string) ([]string, error) {
	root, err := filepath.Abs(s.Root)
	if err != nil {
		return nil, err
	}
	if _, err := os.Stat(root); os.IsNotExist(err) {
		return nil, nil
	}
	pref := strings.TrimPrefix(filepath.ToSlash(prefix), "/")
	var out []string
	err = filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		key := filepath.ToSlash(rel)
		if pref == "" || strings.HasPrefix(key, pref) {
			out = append(out, key)
		}
		return nil
	})
	return out, err
}

func (s *Local) DeletePrefix(_ context.Context, prefix string) error {
	pref := strings.TrimPrefix(filepath.ToSlash(prefix), "/")
	if pref == "" {
		return os.ErrInvalid
	}
	root, err := filepath.Abs(s.Root)
	if err != nil {
		return err
	}
	base := filepath.Join(root, filepath.FromSlash(strings.TrimSuffix(pref, "/")))
	abs, err := filepath.Abs(base)
	if err != nil {
		return err
	}
	if abs != root && !strings.HasPrefix(abs, root+string(os.PathSeparator)) {
		return os.ErrInvalid
	}
	if err := os.RemoveAll(abs); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

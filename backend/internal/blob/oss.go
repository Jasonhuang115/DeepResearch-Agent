package blob

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base64"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"

	"deepresearch/internal/config"
)

type OSS struct {
	AccessKeyID     string
	AccessKeySecret string
	Bucket          string
	Endpoint        string
	Client          *http.Client
}

func NewOSS(cfg config.Config) *OSS {
	ep := strings.TrimSpace(cfg.OSSEndpoint)
	ep = strings.TrimPrefix(ep, "https://")
	ep = strings.TrimPrefix(ep, "http://")
	return &OSS{
		AccessKeyID:     strings.TrimSpace(cfg.OSSAccessKeyID),
		AccessKeySecret: strings.TrimSpace(cfg.OSSAccessKeySecret),
		Bucket:          strings.TrimSpace(cfg.OSSBucket),
		Endpoint:        ep,
		Client:          &http.Client{Timeout: 30 * time.Second},
	}
}

func (s *OSS) baseURL() string {
	return "https://" + s.Bucket + "." + s.Endpoint
}

func (s *OSS) Put(ctx context.Context, key string, data []byte) error {
	req, err := s.newReq(ctx, http.MethodPut, "/"+key, data, "application/octet-stream", "")
	if err != nil {
		return err
	}
	return s.doDiscard(req)
}

func (s *OSS) Get(ctx context.Context, key string) ([]byte, error) {
	req, err := s.newReq(ctx, http.MethodGet, "/"+key, nil, "", "")
	if err != nil {
		return nil, err
	}
	resp, err := s.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, os.ErrNotExist
	}
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return nil, fmt.Errorf("oss get %s: %s %s", key, resp.Status, body)
	}
	return io.ReadAll(resp.Body)
}

func (s *OSS) List(ctx context.Context, prefix string) ([]string, error) {
	var out []string
	marker := ""
	for {
		q := url.Values{}
		q.Set("prefix", prefix)
		q.Set("max-keys", "1000")
		if marker != "" {
			q.Set("marker", marker)
		}
		req, err := s.newReq(ctx, http.MethodGet, "/", nil, "", q.Encode())
		if err != nil {
			return nil, err
		}
		resp, err := s.Client.Do(req)
		if err != nil {
			return nil, err
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			return nil, err
		}
		if resp.StatusCode >= 300 {
			return nil, fmt.Errorf("oss list: %s %s", resp.Status, body)
		}
		var parsed listBucketResult
		if err := xml.Unmarshal(body, &parsed); err != nil {
			return nil, err
		}
		for _, c := range parsed.Contents {
			if c.Key != "" {
				out = append(out, c.Key)
			}
		}
		if !parsed.IsTruncated {
			break
		}
		marker = parsed.NextMarker
		if marker == "" && len(parsed.Contents) > 0 {
			marker = parsed.Contents[len(parsed.Contents)-1].Key
		}
		if marker == "" {
			break
		}
	}
	return out, nil
}

func (s *OSS) DeletePrefix(ctx context.Context, prefix string) error {
	if strings.TrimSpace(prefix) == "" {
		return os.ErrInvalid
	}
	keys, err := s.List(ctx, prefix)
	if err != nil {
		return err
	}
	for _, key := range keys {
		req, err := s.newReq(ctx, http.MethodDelete, "/"+key, nil, "", "")
		if err != nil {
			return err
		}
		if err := s.doDiscard(req); err != nil {
			return err
		}
	}
	return nil
}

func (s *OSS) doDiscard(req *http.Request) error {
	resp, err := s.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("oss %s %s: %s %s", req.Method, req.URL.Path, resp.Status, body)
	}
	return nil
}

func (s *OSS) newReq(ctx context.Context, method, path string, body []byte, contentType, rawQuery string) (*http.Request, error) {
	u, err := url.Parse(s.baseURL() + path)
	if err != nil {
		return nil, err
	}
	if rawQuery != "" {
		u.RawQuery = rawQuery
	}
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, u.String(), rdr)
	if err != nil {
		return nil, err
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	date := time.Now().UTC().Format(http.TimeFormat)
	req.Header.Set("Date", date)
	resource := "/" + s.Bucket + path
	if rawQuery != "" {
		resource += "?" + canonicalOSSQuery(rawQuery)
	}
	req.Header.Set("Authorization", "OSS "+s.AccessKeyID+":"+signOSS(method, "", contentType, date, resource, s.AccessKeySecret))
	return req, nil
}

func canonicalOSSQuery(rawQuery string) string {
	vals, err := url.ParseQuery(rawQuery)
	if err != nil {
		return rawQuery
	}
	keys := make([]string, 0, len(vals))
	for k := range vals {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		v := vals.Get(k)
		if v == "" {
			parts = append(parts, k)
			continue
		}
		parts = append(parts, k+"="+v)
	}
	return strings.Join(parts, "&")
}

func signOSS(method, contentMD5, contentType, date, resource, secret string) string {
	raw := strings.Join([]string{method, contentMD5, contentType, date, resource}, "\n")
	mac := hmac.New(sha1.New, []byte(secret))
	_, _ = mac.Write([]byte(raw))
	return base64.StdEncoding.EncodeToString(mac.Sum(nil))
}

type listBucketResult struct {
	IsTruncated bool   `xml:"IsTruncated"`
	NextMarker  string `xml:"NextMarker"`
	Contents    []struct {
		Key string `xml:"Key"`
	} `xml:"Contents"`
}

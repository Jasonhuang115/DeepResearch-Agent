package blob

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestOSSDeletePrefixListsThenDeletes(t *testing.T) {
	var deleted []string
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && r.URL.Path == "/" {
			io.WriteString(w, `<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult>
  <IsTruncated>false</IsTruncated>
  <Contents><Key>tenants/ten_a/conversations/conv_a/sources/src_03.md</Key></Contents>
  <Contents><Key>tenants/ten_a/conversations/conv_a/tool-output/run/tc.txt</Key></Contents>
</ListBucketResult>`)
			return
		}
		if r.Method == http.MethodDelete {
			deleted = append(deleted, strings.TrimPrefix(r.URL.Path, "/"))
			w.WriteHeader(http.StatusNoContent)
			return
		}
		t.Errorf("unexpected %s %s", r.Method, r.URL.String())
		w.WriteHeader(http.StatusBadRequest)
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	store := &OSS{
		AccessKeyID:     "ak",
		AccessKeySecret: "sk",
		Bucket:          "deepresearch123",
		Endpoint:        u.Host,
		Client:          srv.Client(),
	}
	store.Client.Transport = rewriteHost{base: srv.Client().Transport, host: u.Host}
	ctx := context.Background()
	if err := store.DeletePrefix(ctx, "tenants/ten_a/conversations/conv_a/"); err != nil {
		// httptest URL is https://127.0.0.1:port; client will call https://bucket.127.0.0.1:port
		// so we need a transport that redirects to srv.URL.
		t.Fatal(err)
	}
	if len(deleted) != 2 {
		t.Fatalf("deleted %v", deleted)
	}
}

type rewriteHost struct {
	base http.RoundTripper
	host string
}

func (r rewriteHost) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	clone.URL.Scheme = "https"
	clone.URL.Host = r.host
	clone.Host = r.host
	if r.base == nil {
		return http.DefaultTransport.RoundTrip(clone)
	}
	return r.base.RoundTrip(clone)
}

func TestSignOSSStable(t *testing.T) {
	got := signOSS("DELETE", "", "", "Mon, 02 Jan 2006 15:04:05 GMT", "/bucket/tenants/a/x", "secret")
	again := signOSS("DELETE", "", "", "Mon, 02 Jan 2006 15:04:05 GMT", "/bucket/tenants/a/x", "secret")
	if got == "" || got != again {
		t.Fatalf("%s", got)
	}
}

func TestCanonicalQuerySorted(t *testing.T) {
	got := canonicalOSSQuery("prefix=tenants%2Fa%2F&max-keys=1000")
	if got != "max-keys=1000&prefix=tenants/a/" {
		t.Fatalf("%s", got)
	}
}

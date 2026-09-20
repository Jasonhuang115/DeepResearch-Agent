package upload

import (
	"os"
	"strings"
	"testing"
)

func TestClassifyPDFAndDOCX(t *testing.T) {
	pdf, err := Classify("report.PDF", []byte("%PDF-1.4 fake"))
	if err != nil {
		t.Fatal(err)
	}
	if pdf.ContentType != "application/pdf" || pdf.Filename != "report.PDF" {
		t.Fatalf("%+v", pdf)
	}
	docx, err := Classify("notes.docx", []byte("PK\x03\x04rest"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(docx.ContentType, "wordprocessingml") {
		t.Fatalf("%+v", docx)
	}
	bomPDF, err := Classify("bom.pdf", append([]byte("\xef\xbb\xbf"), []byte("%PDF-1.7 x")...))
	if err != nil {
		t.Fatal(err)
	}
	if bomPDF.ContentType != "application/pdf" {
		t.Fatalf("%+v", bomPDF)
	}
}

func TestClassifyRejects(t *testing.T) {
	cases := []struct {
		name string
		data []byte
	}{
		{"x.exe", []byte("MZ")},
		{"a.pdf", []byte("not a pdf")},
		{"a.docx", []byte("plain")},
		{"a.txt", []byte("ok\x00no")},
		{"", []byte("x")},
		{"a.txt", []byte{}},
	}
	for _, c := range cases {
		if _, err := Classify(c.name, c.data); err == nil {
			t.Fatalf("expected error for %q", c.name)
		}
	}
}

func TestWriteAndAbsJail(t *testing.T) {
	root := t.TempDir()
	rel, err := Write(root, "att_abc", []byte("hello"))
	if err != nil {
		t.Fatal(err)
	}
	abs, err := Abs(root, rel)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(abs)
	if string(got) != "hello" {
		t.Fatalf("got %q", got)
	}
	inside, err := Abs(root, "../secret")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(inside, root) {
		t.Fatalf("escaped to %s", inside)
	}
}

-- +goose Up
CREATE TABLE attachments (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id         VARCHAR(40)     NOT NULL,
    tenant_id         BIGINT UNSIGNED NOT NULL,
    user_id           BIGINT UNSIGNED NOT NULL,
    conversation_id   BIGINT UNSIGNED NOT NULL,
    message_id        BIGINT UNSIGNED NOT NULL,
    filename          VARCHAR(255)    NOT NULL,
    content_type      VARCHAR(127)    NOT NULL,
    size_bytes        BIGINT UNSIGNED NOT NULL,
    sha256            CHAR(64)        NOT NULL,
    storage_path      VARCHAR(512)    NOT NULL,
    created_at        DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_att_public (public_id),
    KEY idx_att_message (tenant_id, message_id),
    KEY idx_att_conv (tenant_id, conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- +goose Down
DROP TABLE IF EXISTS attachments;

CREATE DATABASE CloudEvent;
SHOW DATABASES;
USE CloudEvent;

CREATE TABLE Message (
    message_record_id INT AUTO_INCREMENT PRIMARY KEY,
    message_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload TEXT NOT NULL,
    published_timestamp DATETIME NOT NULL,
    received_timestamp DATETIME NOT NULL,
    processed_timestamp DATETIME NOT NULL,
    is_duplicate BOOLEAN DEFAULT FALSE);
    
CREATE TABLE UserRole (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    role_type VARCHAR(20) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
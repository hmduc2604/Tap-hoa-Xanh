-- Database-per-service: mỗi microservice có một database riêng.
-- Script chạy tự động MỘT LẦN khi volume PostgreSQL được tạo lần đầu.
CREATE DATABASE auth_db;
CREATE DATABASE product_db;
CREATE DATABASE inventory_db;
CREATE DATABASE cart_db;
CREATE DATABASE order_db;
CREATE DATABASE payment_db;
CREATE DATABASE promotion_db;
CREATE DATABASE notification_db;

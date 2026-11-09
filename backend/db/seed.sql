-- SignIA - Datos de prueba (ficticios)
-- Ejecutar después de schema.sql: psql -U user -d signia -f db/seed.sql

-- Password: "test1234" (hash bcrypt, costo 12)
INSERT INTO users (username, email, password_hash) VALUES
('test_user', 'test@signia.cl', '$2b$12$LJ3m4ys3Gv0KqJqJqJqJqOu8KqJqJqJqJqJqJqJqJqJqJqJqJqJqJq');

-- Historial de ejemplo
INSERT INTO history (user_id, predicted_label, spanish_text, confidence, mode) VALUES
(1, 'HOLA', '¡Hola!', 0.94, 'dynamic'),
(1, 'GRACIAS', 'Gracias', 0.87, 'dynamic'),
(1, 'A', 'A', 0.91, 'static'),
(1, 'AYUDA', 'Ayuda', 0.78, 'dynamic');

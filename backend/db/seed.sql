-- SignIA - Datos de prueba (ficticios). SOLO para desarrollo: nunca en producción.
-- Idempotente: puede ejecutarse varias veces sin duplicar datos.
-- Ejecutar después de schema.sql (desde WSL):
--   psql -h 127.0.0.1 -U postgres -d signia -f db/seed.sql
-- Alternativa sin psql (Windows): python -m app.db.seed

-- Usuario: test_user / Password: "Test1234!" (Argon2id, m=65536, t=3, p=4)
INSERT INTO users (username, email, password_hash) VALUES
('test_user', 'test@signia.cl',
 '$argon2id$v=19$m=65536,t=3,p=4$gYsMooF/+o4APBX9XvCYfg$vVdSbwFfSt72EBTB8YdJO8QU7kloHOugK/7i5b22AMQ')
ON CONFLICT (username) DO NOTHING;

-- Historial de ejemplo (etiquetas del modelo v3), solo si el usuario aún no tiene historial
INSERT INTO history (user_id, predicted_label, spanish_text, confidence, mode)
SELECT u.id, v.predicted_label, v.spanish_text, v.confidence, 'dynamic'
FROM users u
CROSS JOIN (VALUES
    ('hola', 'hola', 0.94),
    ('gracias', 'gracias', 0.87),
    ('buenos_dias', 'buenos dias', 0.81),
    ('donde_salida.I', '¿donde salida?', 0.78)
) AS v(predicted_label, spanish_text, confidence)
WHERE u.username = 'test_user'
  AND NOT EXISTS (SELECT 1 FROM history h WHERE h.user_id = u.id);

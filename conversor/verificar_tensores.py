import os
import numpy as np

TENSORES_DIR = os.path.join("dataset", "tensores")
FORMA_ESPERADA = (30, 1629)
TIPO_ESPERADO = np.float32

def auditar_dataset():
    if not os.path.exists(TENSORES_DIR):
        print(f"Error: No se encontró el directorio {TENSORES_DIR}")
        return

    rutas_npy = []
    for root, _, files in os.walk(TENSORES_DIR):
        for file in files:
            if file.endswith(".npy"):
                rutas_npy.append(os.path.join(root, file))

    total_archivos = len(rutas_npy)
    print(f"Total de tensores encontrados: {total_archivos} (Deberían ser 186)")

    errores_shape = 0
    errores_dtype = 0
    errores_nan = 0
    errores_vacios = 0

    for ruta in rutas_npy:
        tensor = np.load(ruta)
        
        # 1. Verificar dimensionalidad
        if tensor.shape != FORMA_ESPERADA:
            print(f"[SHAPE ERROR] {ruta}: {tensor.shape}")
            errores_shape += 1
            
        # 2. Verificar tipo de dato
        if tensor.dtype != TIPO_ESPERADO:
            print(f"[DTYPE ERROR] {ruta}: {tensor.dtype}")
            errores_dtype += 1
            
        # 3. Verificar valores nulos (NaN)
        if np.isnan(tensor).any():
            print(f"[NAN ERROR] {ruta} contiene valores NaN.")
            errores_nan += 1
            
        # 4. Verificar si el tensor está completamente vacío (puros ceros)
        if not np.any(tensor):
            print(f"[EMPTY ERROR] {ruta} está compuesto enteramente de ceros.")
            errores_vacios += 1

    print("\n--- RESUMEN DE AUDITORÍA ---")
    if errores_shape == 0 and errores_dtype == 0 and errores_nan == 0 and errores_vacios == 0:
        print("✅ Todos los tensores pasaron la verificación. Listos para la LSTM.")
    else:
        print(f"❌ Errores de dimensionalidad: {errores_shape}")
        print(f"❌ Errores de tipo de dato: {errores_dtype}")
        print(f"❌ Errores por valores NaN: {errores_nan}")
        print(f"⚠️  Tensores vacíos (sin detección): {errores_vacios}")

if __name__ == "__main__":
    auditar_dataset()
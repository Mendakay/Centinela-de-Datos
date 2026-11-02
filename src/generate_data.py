
 # Bloque de imports
 
import yaml
import pandas as pd
import numpy as np
from faker import Faker
from pathlib import Path
from datetime import datetime, timedelta


#load_config = el nombre de la función ("cargar configuración").
#config_path = un parámetro (una entrada que le puedes pasar).
#="config/config.yaml" = un valor por defecto. Si no le pasas nada, usa ese.
def load_config(config_path="config/config.yaml"):
    """Lee el archivo de configuración YAML."""
    #"Abre el archivo config_path en modo lectura ("r" = read), con codificación utf-8 (para tildes y ñ), y llámalo file mientras lo uso."
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def generate_dirty_excels(config):
    """Genera los 3 Excels sucios basados en la configuración."""
    # 1. Extraer variables del config
    #Saca "data/raw" del diccionario y lo convierte en un objeto Path (una ruta de carpeta manejable)
    raw_path = Path(config["paths"]["inbox"])  # Simula la fuente: deja los Excels en la bandeja de entrada
    #Saca el número de filas (1200)
    num_rows = config["generation"]["num_rows"]
    #Saca la semilla (42)
    seed = config["generation"]["seed"]
    
    # 2. Asegurar que la carpeta exista
    raw_path.mkdir(parents=True, exist_ok=True)
    
    # 3. Fijar semillas para reproducibilidad
    np.random.seed(seed)
    Faker.seed(seed)
    fake = Faker()

    # --- GENERAR ARCHIVO 1: VENTAS (Fechas mixtas) ---
    fechas_ventas = []
    for _ in range(num_rows):
        base_date = datetime(2024, 1, 1) + timedelta(days=np.random.randint(0, 365))
        tipo_formato = np.random.choice(["datetime", "string_dmy", "string_iso"])
        
        if tipo_formato == "datetime":
            fechas_ventas.append(base_date) # Objeto fecha real
        elif tipo_formato == "string_dmy":
            fechas_ventas.append(base_date.strftime("%d/%m/%Y")) # 15/03/2024
        else:
            fechas_ventas.append(base_date.strftime("%Y-%m-%d")) # 2024-03-15

    df_ventas = pd.DataFrame({
        "id": range(1, num_rows + 1),
        "fecha": fechas_ventas,
        "cliente": [f"  {fake.name()}  " for _ in range(num_rows)], # Espacios extra
        "monto": np.random.uniform(10, 5000, num_rows).round(2)
    })
    df_ventas.to_excel(raw_path / config["generation"]["files"]["ventas"], index=False)

    # --- GENERAR ARCHIVO 2: CLIENTES (Columnas con nombres distintos) ---
    df_clientes = pd.DataFrame({
        "ID_Cliente": range(1000, 1000 + num_rows),
        "Nombre Completo": [fake.name().replace(" ", "  ", 1) for _ in range(num_rows)], # Doble espacio
        "Fecha_Alta": [fake.date_between(start_date="-2y", end_date="today").strftime("%d-%m-%Y") for _ in range(num_rows)]
    })
    df_clientes.to_excel(raw_path / config["generation"]["files"]["clientes"], index=False)

    # --- GENERAR ARCHIVO 3: PRODUCTOS (Nulos y tipos mezclados) ---
    df_productos = pd.DataFrame({
        "sku": [f"SKU-{i:04d}" for i in range(1, num_rows + 1)],
        "descripcion": [fake.catch_phrase() if np.random.random() > 0.1 else None for _ in range(num_rows)], # 10% nulos
        "precio_unitario": [str(round(np.random.uniform(5, 200), 2)) if np.random.random() > 0.5 else round(np.random.uniform(5, 200), 2) for _ in range(num_rows)], # Mezcla strings y floats
        "fecha_ingreso": [fake.date_this_year().strftime("%Y/%m/%d") for _ in range(num_rows)] # Formato con slash
    })
    df_productos.to_excel(raw_path / config["generation"]["files"]["productos"], index=False)

    print(f"✅ 3 archivos sucios generados exitosamente en: {raw_path}")

if __name__ == "__main__":
    config_data = load_config()
    generate_dirty_excels(config_data)
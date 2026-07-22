"""
test_carga.py — Prueba de distribución de tráfico y disponibilidad NGINX

PROPÓSITO: Verificar que el balanceador NGINX distribuye el tráfico
en la proporción 3:2:1 (Nodo 1 ~50%, Nodo 2 ~33%, Nodo 3 ~17%).

NOTA: Esta prueba usa /health (sin sesión, sin MySQL, sin templates complejos)
y NO representa la latencia real del sistema bajo carga. La prueba de
rendimiento real es Locust (load_tests/locustfile.py).

Exporta: resultados/balanceo.csv

Ejecución:
  python test_carga.py
"""

import concurrent.futures
import requests
import time
import re
import csv
import os
import statistics

# Configuración
URL              = "http://localhost/health"
TOTAL_REQUESTS   = 120
CONCURRENT_CLIENTS = 10
CSV_DIR          = os.path.join(os.path.dirname(__file__), "resultados")
CSV_PATH         = os.path.join(CSV_DIR, "balanceo.csv")


def send_request(request_id):
    start_time = time.time()
    try:
        response = requests.get(URL, timeout=5)
        latency  = time.time() - start_time
        if response.status_code == 200:
            try:
                data = response.json()
                node = data.get("node", "Desconocido")
            except Exception:
                # Fallback: buscar el nodo en el HTML si el endpoint devuelve HTML
                match = re.search(r'"node":\s*"([^"]+)"', response.text)
                node  = match.group(1).strip() if match else "Desconocido"
            return {"success": True, "latency": latency, "node": node, "id": request_id}
        else:
            return {"success": False, "latency": latency, "node": None,
                    "error": f"HTTP {response.status_code}", "id": request_id}
    except Exception as e:
        latency = time.time() - start_time
        return {"success": False, "latency": latency, "node": None,
                "error": str(e), "id": request_id}


def percentil(datos, p):
    """Calcula el percentil p de una lista ordenada."""
    if not datos:
        return 0
    datos_ord = sorted(datos)
    idx = int(len(datos_ord) * p / 100)
    idx = min(idx, len(datos_ord) - 1)
    return datos_ord[idx]


def run_load_test():
    print("=" * 58)
    print("  PRUEBA DE DISTRIBUCIÓN DE TRÁFICO — NGINX (3:2:1)")
    print("=" * 58)
    print(f"Endpoint    : {URL}")
    print(f"Peticiones  : {TOTAL_REQUESTS}")
    print(f"Concurrencia: {CONCURRENT_CLIENTS} hilos\n")
    print("Enviando peticiones, por favor espera...")

    start_test = time.time()
    results    = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_CLIENTS) as executor:
        futures = [executor.submit(send_request, i) for i in range(TOTAL_REQUESTS)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    duracion      = time.time() - start_test
    exitosas      = [r for r in results if r["success"]]
    fallidas      = [r for r in results if not r["success"]]
    latencias     = [r["latency"] for r in exitosas]

    rps_total     = TOTAL_REQUESTS / duracion
    rps_exitosas  = len(exitosas) / duracion

    avg_latency   = statistics.mean(latencias) if latencias else 0
    p50           = percentil(latencias, 50)
    p95           = percentil(latencias, 95)
    p99           = percentil(latencias, 99)
    max_latency   = max(latencias) if latencias else 0

    # Distribución por nodo
    node_distribution = {}
    for r in exitosas:
        node = r["node"] or "Desconocido"
        node_distribution[node] = node_distribution.get(node, 0) + 1

    # ---- Imprimir métricas ----
    print("\n" + "=" * 58)
    print("  MÉTRICAS DE DESEMPEÑO")
    print("=" * 58)
    print(f"Duración total          : {duracion:.3f} s")
    print(f"Peticiones exitosas     : {len(exitosas)} ({len(exitosas)/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Peticiones fallidas     : {len(fallidas)} ({len(fallidas)/TOTAL_REQUESTS*100:.1f}%)")
    print(f"RPS total               : {rps_total:.1f} req/s")
    print(f"RPS exitosas            : {rps_exitosas:.1f} req/s")
    print(f"Latencia promedio       : {avg_latency*1000:.1f} ms")
    print(f"Latencia P50            : {p50*1000:.1f} ms")
    print(f"Latencia P95            : {p95*1000:.1f} ms")
    print(f"Latencia P99            : {p99*1000:.1f} ms")
    print(f"Latencia máxima         : {max_latency*1000:.1f} ms")

    # ---- Distribución NGINX ----
    print("\n" + "=" * 58)
    print("  DISTRIBUCIÓN DE CARGA (NGINX) — esperado 3:2:1")
    print("  Nodo 1 ≈ 50%  |  Nodo 2 ≈ 33%  |  Nodo 3 ≈ 17%")
    print("=" * 58)
    esperados = {
        "Nodo 1 (Capacidad Alta)": 50.0,
        "Nodo 2 (Capacidad Media)": 33.3,
        "Nodo 3 (Capacidad Baja)": 16.7,
    }
    for nodo, count in sorted(node_distribution.items()):
        pct_real     = (count / len(exitosas)) * 100 if exitosas else 0
        pct_esperado = esperados.get(nodo, 0)
        barra        = "█" * int(pct_real // 2)
        print(f"{nodo:<28}: {count:<4} peticiones "
              f"(real {pct_real:5.1f}% / esperado {pct_esperado:.1f}%) {barra}")

    # ---- Exportar CSV ----
    os.makedirs(CSV_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["request_id", "success", "node", "latency_ms", "error"])
        for r in sorted(results, key=lambda x: x["id"]):
            writer.writerow([
                r["id"],
                r["success"],
                r.get("node", ""),
                f"{r['latency']*1000:.2f}",
                r.get("error", ""),
            ])
    print(f"\nCSV exportado: {CSV_PATH}")


if __name__ == "__main__":
    run_load_test()

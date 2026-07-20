import concurrent.futures
import requests
import time
import re

# URL del Balanceador de Carga NGINX
URL = "http://localhost/login"
TOTAL_REQUESTS = 120  # Número total de peticiones
CONCURRENT_CLIENTS = 10  # Clientes concurrentes (hilos)

def send_request(request_id):
    start_time = time.time()
    try:
        response = requests.get(URL, timeout=5)
        latency = time.time() - start_time
        if response.status_code == 200:
            # Buscar el nodo usando una expresión regular en el HTML
            # Formato esperado: Atendido por: <span class="badge-node">Nodo X (Capacidad ...)</span>
            match = re.search(r'class="badge-node">([^<]+)</span>', response.text)
            node = match.group(1).strip() if match else "Desconocido"
            return {"success": True, "latency": latency, "node": node}
        else:
            return {"success": False, "latency": latency, "node": None, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        latency = time.time() - start_time
        return {"success": False, "latency": latency, "node": None, "error": str(e)}

def run_load_test():
    print(f"=== INICIANDO PRUEBA DE CARGA CONCURRENTE ===")
    print(f"Destino: {URL}")
    print(f"Peticiones Totales: {TOTAL_REQUESTS}")
    print(f"Clientes Concurrentes: {CONCURRENT_CLIENTS}\n")
    print("Enviando peticiones, por favor espera...")
    
    start_test = time.time()
    results = []
    
    # Ejecución de peticiones de manera concurrente usando un pool de hilos
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_CLIENTS) as executor:
        futures = [executor.submit(send_request, i) for i in range(TOTAL_REQUESTS)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            
    total_test_time = time.time() - start_test
    
    # Procesar resultados
    success_count = sum(1 for r in results if r["success"])
    failed_count = TOTAL_REQUESTS - success_count
    
    latencies = [r["latency"] for r in results if r["success"]]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    
    # Contar peticiones por nodo
    node_distribution = {}
    for r in results:
        if r["success"] and r["node"]:
            node = r["node"]
            node_distribution[node] = node_distribution.get(node, 0) + 1
            
    # Presentar métricas
    print("\n================ METRICAS DE DESEMPEÑO ================")
    print(f"Tiempo Total de la Prueba: {total_test_time:.3f} segundos")
    print(f"Peticiones Exitosas:       {success_count} ({success_count/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Peticiones Fallidas:       {failed_count} ({failed_count/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Tiempo de Respuesta Mínimo: {min_latency*1000:.1f} ms")
    print(f"Tiempo de Respuesta Máximo: {max_latency*1000:.1f} ms")
    print(f"Tiempo de Respuesta Promedio: {avg_latency*1000:.1f} ms")
    print(f"Throughput (Rendimiento):  {TOTAL_REQUESTS/total_test_time:.1f} peticiones/seg")
    
    print("\n============= DISTRIBUCIÓN DE CARGA (NGINX) =============")
    print("Distribución esperada por pesos (3:2:1) -> Nodo 1 (~50%), Nodo 2 (~33%), Nodo 3 (~17%)\n")
    
    sorted_nodes = sorted(node_distribution.items(), key=lambda x: x[0])
    for node_name, count in sorted_nodes:
        percentage = (count / success_count) * 100 if success_count else 0
        bar = "█" * int(percentage // 2)
        print(f"{node_name:<28}: {count:<4} peticiones ({percentage:.1f}%) {bar}")

if __name__ == "__main__":
    run_load_test()

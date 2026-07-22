# monitor_recursos.ps1 — Monitor de recursos de contenedores Docker
#
# Captura métricas de CPU y memoria de todos los contenedores en ejecución
# a intervalos regulares y las guarda en resultados/docker_stats.csv.
#
# Parámetros:
#   -DuracionSegundos : cuántos segundos capturar (por defecto 180)
#   -IntervaloSegundos: intervalo entre muestras en segundos (por defecto 5)
#   -ArchivoSalida    : ruta del CSV de salida
#
# Uso:
#   .\scripts\monitor_recursos.ps1 -DuracionSegundos 180
#   .\scripts\monitor_recursos.ps1 -DuracionSegundos 60 -IntervaloSegundos 2

param(
    [int]    $DuracionSegundos  = 180,
    [int]    $IntervaloSegundos = 5,
    [string] $ArchivoSalida     = "resultados\docker_stats.csv"
)

# Resolver ruta relativa al directorio del script (cod-mp/)
$RaizProyecto = Split-Path -Parent $PSScriptRoot
$RutaCSV      = Join-Path $RaizProyecto $ArchivoSalida

# Crear directorio si no existe
$Directorio = Split-Path -Parent $RutaCSV
if (-not (Test-Path $Directorio)) {
    New-Item -ItemType Directory -Path $Directorio -Force | Out-Null
}

# Escribir encabezado del CSV
"timestamp,contenedor,cpu_pct,mem_uso,mem_limite,mem_pct,net_io,block_io" |
    Set-Content -Path $RutaCSV -Encoding UTF8

Write-Host "==================================================="
Write-Host "  MONITOR DE RECURSOS — Docker Stats"
Write-Host "==================================================="
Write-Host "Duración   : $DuracionSegundos segundos"
Write-Host "Intervalo  : $IntervaloSegundos segundos"
Write-Host "Salida     : $RutaCSV"
Write-Host "---------------------------------------------------"
Write-Host "Iniciando captura... (Ctrl+C para detener antes)"
Write-Host ""

$inicio    = Get-Date
$fin       = $inicio.AddSeconds($DuracionSegundos)
$muestras  = 0

while ((Get-Date) -lt $fin) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

    # docker stats --no-stream devuelve una línea por contenedor
    $stats = docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}" 2>$null

    if ($stats) {
        foreach ($linea in $stats) {
            # Separar campos
            $campos = $linea -split ","
            if ($campos.Count -ge 6) {
                $contenedor = $campos[0].Trim()
                $cpu        = $campos[1].Trim()
                $mem_raw    = $campos[2].Trim()     # e.g. "45.2MiB / 512MiB"
                $mem_pct    = $campos[3].Trim()
                $net_io     = $campos[4].Trim()
                $block_io   = $campos[5].Trim()

                # Dividir mem_uso y mem_limite
                $mem_partes  = $mem_raw -split " / "
                $mem_uso     = if ($mem_partes.Count -ge 1) { $mem_partes[0] } else { $mem_raw }
                $mem_limite  = if ($mem_partes.Count -ge 2) { $mem_partes[1] } else { "" }

                # Escapar comas en campos de IO
                $net_io_esc   = '"' + $net_io   + '"'
                $block_io_esc = '"' + $block_io + '"'

                "$timestamp,$contenedor,$cpu,$mem_uso,$mem_limite,$mem_pct,$net_io_esc,$block_io_esc" |
                    Add-Content -Path $RutaCSV -Encoding UTF8
            }
        }
        $muestras++
        Write-Host "[$timestamp] Muestra $muestras registrada — $(@($stats).Count) contenedor(es)"
    } else {
        Write-Host "[$timestamp] Sin contenedores activos o Docker no disponible."
    }

    Start-Sleep -Seconds $IntervaloSegundos
}

Write-Host ""
Write-Host "==================================================="
Write-Host "  Captura finalizada. $muestras muestras registradas."
Write-Host "  Archivo: $RutaCSV"
Write-Host "==================================================="

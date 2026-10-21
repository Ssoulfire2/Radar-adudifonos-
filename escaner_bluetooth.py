"""
Escáner Bluetooth LE - Aplicación de escritorio
Requiere: pip install bleak
"""
import asyncio
import csv
import queue
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from bleak import BleakScanner

SEGUNDOS_INACTIVO = 30   # Quitar dispositivos que no se ven hace X segundos
MUESTRAS_RSSI = 5        # Promedio de las últimas N lecturas (estabiliza la distancia)


def estimar_distancia(rssi, potencia_1m, factor):
    if rssi is None or rssi == 0:
        return None
    return 10 ** ((potencia_1m - rssi) / (10 * factor))


class EscanerBLE:
    """Ejecuta bleak en un hilo aparte para no congelar la interfaz."""

    def __init__(self, cola):
        self.cola = cola
        self.loop = None
        self.stop_event = None
        self.activo = False

    def iniciar(self):
        if self.activo:
            return
        self.activo = True
        threading.Thread(target=self._run, daemon=True).start()

    def detener(self):
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def _run(self):
        try:
            asyncio.run(self._escanear())
        except Exception as e:
            self.cola.put(("error", str(e)))
        finally:
            self.activo = False
            self.cola.put(("fin", None))

    async def _escanear(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()

        def callback(device, adv):
            nombre = device.name or adv.local_name or "Dispositivo sin nombre"
            self.cola.put(("disp", (device.address, nombre, adv.rssi)))

        async with BleakScanner(detection_callback=callback):
            await self.stop_event.wait()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Escáner Bluetooth")
        self.geometry("760x520")
        self.minsize(640, 420)

        self.cola = queue.Queue()
        self.escaner = EscanerBLE(self.cola)
        self.dispositivos = {}  # address -> dict

        self.var_max = tk.DoubleVar(value=10)
        self.var_potencia = tk.DoubleVar(value=-59)
        self.var_factor = tk.DoubleVar(value=2.5)

        self._crear_ui()
        self.after(150, self._procesar_cola)
        self.after(500, self._refrescar_tabla)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

    # ---------- Interfaz ----------
    def _crear_ui(self):
        # Botones
        barra = ttk.Frame(self, padding=8)
        barra.pack(fill="x")
        self.btn_iniciar = ttk.Button(barra, text="▶ Iniciar escaneo", command=self.iniciar)
        self.btn_iniciar.pack(side="left")
        self.btn_detener = ttk.Button(barra, text="■ Detener", command=self.detener, state="disabled")
        self.btn_detener.pack(side="left", padx=6)
        ttk.Button(barra, text="Limpiar", command=self.limpiar).pack(side="left")
        ttk.Button(barra, text="Exportar CSV", command=self.exportar).pack(side="right")

        # Ajustes
        ajustes = ttk.LabelFrame(self, text="Ajustes", padding=8)
        ajustes.pack(fill="x", padx=8)
        ajustes.columnconfigure(1, weight=1)

        self._slider(ajustes, 0, "Distancia máxima (m)", self.var_max, 1, 50, "{:.0f}")
        self._slider(ajustes, 1, "RSSI a 1 metro (dBm)", self.var_potencia, -80, -40, "{:.0f}")
        self._slider(ajustes, 2, "Factor de ambiente", self.var_factor, 2.0, 4.0, "{:.1f}")

        # Tabla
        marco = ttk.Frame(self, padding=8)
        marco.pack(fill="both", expand=True)
        columnas = ("nombre", "direccion", "rssi", "distancia")
        self.tabla = ttk.Treeview(marco, columns=columnas, show="headings")
        for col, texto, ancho in (
            ("nombre", "Nombre", 240),
            ("direccion", "Dirección", 170),
            ("rssi", "RSSI (dBm)", 90),
            ("distancia", "Distancia (m)", 100),
        ):
            self.tabla.heading(col, text=texto)
            self.tabla.column(col, width=ancho, anchor="w" if col in ("nombre", "direccion") else "center")
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Barra de estado
        self.estado = tk.StringVar(value="Listo.")
        ttk.Label(self, textvariable=self.estado, relief="sunken", anchor="w", padding=4).pack(fill="x")

    def _slider(self, padre, fila, texto, variable, desde, hasta, formato):
        ttk.Label(padre, text=texto, width=22).grid(row=fila, column=0, sticky="w")
        etiqueta = ttk.Label(padre, text=formato.format(variable.get()), width=6)
        etiqueta.grid(row=fila, column=2)

        def al_mover(v):
            etiqueta.config(text=formato.format(float(v)))

        ttk.Scale(padre, from_=desde, to=hasta, variable=variable, command=al_mover).grid(
            row=fila, column=1, sticky="ew", padx=8)

    # ---------- Acciones ----------
    def iniciar(self):
        self.escaner.iniciar()
        self.btn_iniciar.config(state="disabled")
        self.btn_detener.config(state="normal")
        self.estado.set("Buscando dispositivos Bluetooth cercanos...")

    def detener(self):
        self.escaner.detener()
        self.btn_detener.config(state="disabled")
        self.estado.set("Deteniendo...")

    def limpiar(self):
        self.dispositivos.clear()
        self._refrescar_tabla(reprogramar=False)

    def exportar(self):
        filas = self._filas_visibles()
        if not filas:
            messagebox.showinfo("Exportar", "No hay dispositivos para exportar.")
            return
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"bluetooth_{datetime.now():%Y%m%d_%H%M%S}.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not ruta:
            return
        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Nombre", "Dirección", "RSSI (dBm)", "Distancia (m)"])
            for addr, nombre, rssi, dist in filas:
                w.writerow([nombre, addr, f"{rssi:.0f}", f"{dist:.1f}"])
        self.estado.set(f"Exportado: {ruta}")

    def _cerrar(self):
        self.escaner.detener()
        self.destroy()

    # ---------- Procesamiento ----------
    def _procesar_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "disp":
                    addr, nombre, rssi = dato
                    if rssi is None:
                        continue
                    d = self.dispositivos.setdefault(
                        addr, {"nombre": nombre, "rssis": deque(maxlen=MUESTRAS_RSSI), "visto": 0})
                    # Conserva un nombre real si antes lo teníamos
                    if not nombre.startswith("Dispositivo sin") or d["nombre"].startswith("Dispositivo sin"):
                        d["nombre"] = nombre
                    d["rssis"].append(rssi)
                    d["visto"] = time.time()
                elif tipo == "error":
                    messagebox.showerror(
                        "Error de Bluetooth",
                        f"{dato}\n\nVerifica que el Bluetooth esté activado en tu PC.")
                elif tipo == "fin":
                    self.btn_iniciar.config(state="normal")
                    self.btn_detener.config(state="disabled")
                    self.estado.set("Escaneo detenido.")
        except queue.Empty:
            pass
        self.after(150, self._procesar_cola)

    def _filas_visibles(self):
        ahora = time.time()
        maxima = self.var_max.get()
        potencia = self.var_potencia.get()
        factor = self.var_factor.get()
        filas = []
        for addr, d in list(self.dispositivos.items()):
            if ahora - d["visto"] > SEGUNDOS_INACTIVO or not d["rssis"]:
                continue
            rssi = sum(d["rssis"]) / len(d["rssis"])
            dist = estimar_distancia(rssi, potencia, factor)
            if dist is None or dist > maxima:
                continue
            filas.append((addr, d["nombre"], rssi, dist))
        filas.sort(key=lambda f: f[3])
        return filas

    def _refrescar_tabla(self, reprogramar=True):
        filas = self._filas_visibles()
        presentes = {f[0] for f in filas}

        for iid in self.tabla.get_children():
            if iid not in presentes:
                self.tabla.delete(iid)

        existentes = set(self.tabla.get_children())
        for i, (addr, nombre, rssi, dist) in enumerate(filas):
            valores = (nombre, addr, f"{rssi:.0f}", f"{dist:.1f}")
            if addr in existentes:
                self.tabla.item(addr, values=valores)
            else:
                self.tabla.insert("", "end", iid=addr, values=valores)
            self.tabla.move(addr, "", i)

        if self.escaner.activo:
            self.estado.set(f"Escaneando... {len(filas)} dispositivo(s) dentro de {self.var_max.get():.0f} m")

        if reprogramar:
            self.after(500, self._refrescar_tabla)


if __name__ == "__main__":
    App().mainloop()

#Librerias de PYQT5, para la aplicacion
import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer
from PyQt5 import uic

#Librerias para uso del puerto serial
import serial.tools.list_ports
import serial
import numpy as np
import struct

#Librerias extra
import wfdb #formato de physionet
import os #trabajar con rutas
import time #encontrar el tiempo
from collections import deque #nueva estructura de datos

#Libreria para creacion de hilos
import threading

#Llibrerias para graficar
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

#Creacion de la ventana emergente del histograma
class ventanaHistograma(QDialog):
    def __init__(self, datos):
        super().__init__()
        self.setWindowTitle("Histograma")

        layout = QVBoxLayout(self)

        # Crear figura
        self.fig = Figure(figsize=(5,4))
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Crear eje
        ax = self.fig.add_subplot(111)
        ax.hist(datos, bins=50, weights=np.ones(len(datos)) / len(datos) * 100)
        ax.set_title("Histograma")
        ax.set_xlabel("Amplitud (mV)")
        ax.set_ylabel("Frecuencia (%)")
        ax.grid(True)

        self.canvas.draw()

#Creacion de la ventana principal
class principal(QMainWindow):
    
    def __init__(self):

        # Poner la direccion del desinger para abrir la ventana      
        super(principal,self).__init__()
        
        #busca el .ui en el mismo directorio que el codigo y lo carga
        try: 
            ruta_ui = os.path.join(os.path.dirname(__file__), "interfaz1.ui") #busca activamente el archivo de la interfaz en el mismo directorio
            uic.loadUi(ruta_ui, self)
        except Exception as e:
            print("Error al cargar UI:", e)

        #Define el tamaño de la ventana
        self.resize(1600, 800) 
        
        #Llamar la funcion de verificacion de los puertos de comunicacion
        self.puertosdisponibles()
        self.ser = None
        
        #Llamar la funcion conectar cada vez que se da click sobre un boton
        self.ConectW.clicked.connect(self.conectarCOM)
        self.Guardar.clicked.connect(self.guardarDatos)
        self.Cargar.clicked.connect(self.cargarDatos)
        self.Medidas.clicked.connect(self.medirGrafica)
        self.pHistograma.clicked.connect(self.mostrarHistograma)
        self.chooseOffset.valueChanged.connect(self.cambiarOffset)
        self.pGauss.clicked.connect(self.anadirRuidoGaussiano)
        self.pImpulso.clicked.connect(self.anadirRuidoImpulso)
        self.pArtefacto.clicked.connect(self.anadirRuidoArtefacto)

        #Variables para graficar
        self.frecuenciaSenal = 100 #frecuencia de muestreo
        self.tiempoVisible = 5 #que tanto tiempo se ve en la grafica, en segundos
        self.offset = 0

        #Crear los buffers
        maxlen = int(self.frecuenciaSenal * 30)
        self.buffer1 = deque(maxlen=maxlen)
        self.buffer2 = deque(maxlen=maxlen)
        self.buf_lock = threading.Lock()

        #Variables para ruido
        self.gaussiano = False
        self.impulso = False
        self.artefacto = False
        self.potenciaRuido = 0

        #Creacion de figuras
        self.fig = Figure(figsize=(15,10))
        self.ax = self.fig.add_subplot(111) 
        self.canvas = FigureCanvas(self.fig)
        self.ax.clear()
        self.line, = self.ax.plot([], [])
        self.ax.set_xlabel("Tiempo (s)")
        self.ax.set_ylabel("Amplitud (mV)")
        self.ax.grid(True)
        self.canvas = FigureCanvas(self.fig)

        #Insertar la figura
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.setContentsMargins(200, 50, 50, 50)
        self.graficawidget.setLayout(layout)

        #Timer que actualiza la grafica
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.actualizarGrafica)
        self.update_timer.start(10)  # 50 ms 

        #Variables para prueba
        self.modo_prueba = False   # colocar en false para usar, true para probar sin serial
        self.tri_val = 0
        self.tri_step = 5     
        self.tri_max = 100 #amplitud maxima       
        self.tri_min = 0
        self.tri_dir = 1      

    # Funcion para visualizacion de los puertos COM en uso           
    def puertosdisponibles(self):
        p= serial.tools.list_ports.comports()
        for port in p:
            #visualizar los puertos disponibles en el combo que se llama PuertosW
            self.PuertosW.addItem(port.device)

    # Funcion que abre la ventana del histograma
    def mostrarHistograma(self):      
        with self.buf_lock:
            y = list(self.buffer1)
            max_visible = int(self.tiempoVisible * self.frecuenciaSenal)
            if len(y) > max_visible:
                y = y[-max_visible:]   #Recorta y hasta que alcanza el largo deseado, solo lo visible

        self.ventana = ventanaHistograma(y)
        self.ventana.exec()

    #Funcion que actualiza el valor del offset
    def cambiarOffset(self):
        self.offset = 10*self.chooseOffset.value()

    #Funciones que actualizan que ruido se activa
    def anadirRuidoGaussiano(self):
        if not self.gaussiano:
            self.impulso = False
            self.artefacto = False
            self.gaussiano = True
        elif self.gaussiano:
            self.gaussiano = False

    def anadirRuidoImpulso(self):
        if not self.impulso:
            self.impulso = True
            self.artefacto = False
            self.gaussiano = False
        elif self.impulso:
            self.impulso = False

    def anadirRuidoArtefacto(self):
        if not self.artefacto:
            self.impulso = False
            self.artefacto = True
            self.gaussiano = False
        elif self.artefacto:
            self.artefacto = False

    # Funcion para actualizar los labels de las medidas de tendencia central
    def medirGrafica(self):

        y = list(self.buffer1)
        max_visible = int(self.tiempoVisible * self.frecuenciaSenal)
        if len(y) > max_visible:
            y = y[-max_visible:]
        y = np.array(y, dtype=float)

        #Media
        media = 0
        n = 0
        for i in range(0,len(y),1):
            media += y[i]
            n+=1
        media/=n
        self.lMedia.setText(str(media))

        #Desviacion estandar
        s2 = 0
        for i in range(0,len(y),1):
            s2 += (1/n)*((y[i]-media)**2)
        s = np.sqrt(s2)
        self.lDesviacion.setText(str(s))

        cv = s/media*100
        self.lCoeficiente.setText(str(cv))

        #Curtosis
        g = 0
        for i in range(0,len(y),1):
            g += (1/n)*((y[i]-media)**4)
        print(g)
        g = ((1/n)*g/s**4)-3
        if g == 0:
            self.lCurtosis.setText("Mesocurtica")
        if g > 0:
            self.lCurtosis.setText("Leptocurtica")
        if g < 0:
            self.lCurtosis.setText("Platicurtica")

        #Asimetria
        a = 0
        for i in range(0,len(y),1):
            a += ((y[i]-media)**3)
        a = a/((n-1)*s**3)
        if a>0:
            self.lAsimetria.setText("positiva")
        if a<0:
            self.lAsimetria.setText("negativa")
        if a==0:
            self.lAsimetria.setText("sin")

        #SNR
        pSenal = np.mean(y**2)
        if not self.potenciaRuido == 0:
            snr = 10 * np.log10(pSenal/self.potenciaRuido)
            self.lsnr.setText(str(snr))
        elif self.potenciaRuido == 0:
            self.lsnr.setText("ind")

    # Funcion para guardar el vector de datos en un archivo        
    def guardarDatos(self):

        try:
            ruta, tipoArchivo = QFileDialog.getSaveFileName(
                self,
                "Guardar grafica", #nombre de la ventana
                "registro", #nombre predeterminado del archivo
                "Todos los archivos (*);;WFDB (*.hea);;Archivo de texto (*.txt)" #tipos de archivo disponible
            )

            if not ruta:
                return

            #Si es .txt lo guarda por numpy
            if tipoArchivo.startswith("Archivo de texto"):
                np.savetxt(ruta, self.buffer1, delimiter=",")

            #Si es .hea o .dat lo guarda mediante wfdb
            elif tipoArchivo.startswith("WFDB"):
                
                carpeta = os.path.dirname(ruta) #saca la ruta del archivo
                nombre = os.path.splitext(os.path.basename(ruta))[0] #saca el nombre del archivo
                nombre = nombre.replace(" ", "_") #quita espacios del nombre

                senal = np.asarray(self.buffer1).reshape(-1, 1) #vuelve el buffer un vector compatible para guardarse con wfdb

                wfdb.wrsamp(
                    record_name=nombre, 
                    fs=self.frecuenciaSenal, 
                    units=["mV"],      
                    sig_name=["Canal"],  
                    p_signal=senal,
                    fmt=["16"], #la señal esta a 16bits
                    write_dir=carpeta #ruta del archivo
                )

        except IOError as e:
            print(f"Error: {e}")

    # Funcion para cargar los datos y graficarlos desde un archivo 
    def cargarDatos(self):
    
        ruta, _ = QFileDialog.getOpenFileName(
            self, 
            "Seleccionar Archivo de Datos",
            "", 
            "Todos los archivos (*);;WFDB (*.hea);;Archivo de texto (*.txt)"
        )

        if not ruta:
            return
        
        extension = os.path.splitext(ruta)[1].lower() #saca la extension del archivo desde la ruta del mismo

        try:

            if extension == ".txt":
                datos = np.loadtxt(ruta, delimiter=",") #carga mediante numpy
                self.graficarDatosCargados(datos) 

            elif extension in [".hea", ".dat"]:

                base = os.path.splitext(ruta)[0]

                senales, campos = wfdb.rdsamp(base)

                datos = senales[:, 0]  

                self.graficarDatosCargados(datos)

        except Exception as e:
            print("Error al cargar:", e)

    # Sub Funcion para graficar los datos cargados
    def graficarDatosCargados(self,datos):

        with self.buf_lock:

            #Limpia la grafica
            self.buffer1.clear() 
            self.buffer2.clear()

            #Variables para graficar
            datos = np.array(datos, dtype=float)
            self.ruido = np.zeros(len(datos))

            #Modifica el vector de ruido dependiendo del tipo de ruido
            if self.gaussiano:
                self.ruido = np.random.normal(0.0, 10.0, size=len(datos))

            if self.impulso:
                       
                prob = 0.05  # 5% de los valores tendrán impulso
                for i in range(len(datos)):
                    if np.random.rand() < prob:
                        self.ruido[i] = np.max(datos) if np.random.rand() < 0.5 else np.min(datos)

            if self.artefacto:
                self.ruido = np.zeros(len(datos))
                n_art = 1  # número de artefactos
                dur = 1     # duración de cada artefacto en puntos
                for _ in range(n_art):
                    start = np.random.randint(0, len(datos) - dur)
                    incremento = np.random.uniform(50, 100)  # valor del artefacto
                    self.ruido[start:start+dur] += incremento

            self.potenciaRuido = np.mean(self.ruido**2)
            datos += self.ruido

            now = time.time()
            for v in datos:
                self.buffer1.append(v)
                self.buffer2.append(now)
                now += 1.0 / self.frecuenciaSenal

        self.canvas.draw()

    #Funcion para que se actualize la grafica cada que se activa el timer
    def actualizarGrafica(self):

        #no la actualiza si no hay datos para graficar
        if len(self.buffer1) == 0:
            return

        # copiar buffers
        with self.buf_lock:
            y = list(self.buffer1)
            x = list(self.buffer2)

        # normalizar tiempos
        t0 = x[0]
        x_rel = [t - t0 for t in x]

        # limitar número de muestras a mostrar (ej. last N)
        max_visible = int(self.tiempoVisible * self.frecuenciaSenal)
        if len(x_rel) > max_visible:
            x_rel = x_rel[-max_visible:]
            y = y[-max_visible:]

        # actualizar línea 
        try:
            self.line.set_data(x_rel, y)
            self.ax.relim()
            self.ax.autoscale_view(scalex=True, scaley=True)
            self.ax.set_xlim(max(0, x_rel[-1] - self.tiempoVisible), x_rel[-1])
            self.canvas.draw_idle()
        except Exception as e:
            print("Error actualizando plot:", e)


    #Funcion para conectar al puerto de comunicacion con el boton        
    def conectarCOM(self):
        
        estado= self.ConectW.text()
        self.stop_event_ser= threading.Event()

        if estado == "Conectar":

            self.stop_event_ser = threading.Event()
            self.stop_event_ser.clear()

            with self.buf_lock:
                self.buffer1.clear()
                self.buffer2.clear()

            if not self.modo_prueba: #para que no abra el puerto durante pruebas
                com = self.PuertosW.currentText()
                try:
                    self.ser = serial.Serial(com,115200)
                    self.ser.timeout = 0
                except serial.SerialException as e:
                    print("Error serial:", e)
                    return

            self.hiloserial = threading.Thread(target=self.periodic_thread, daemon=True)
            self.hiloserial.start()

            self.ConectW.setText("Desconectar")
     
        else:
            self.stop_event_ser.set()

            try:
                if self.hiloserial.is_alive():
                    self.hiloserial.join(timeout=1.0)
            except:
                pass

            if self.ser:
                try:
                    self.ser.close()
                except:
                    pass

            self.ConectW.setText("Conectar")

    #funcion para crear el hilo
    def periodic_thread(self):

        while not self.stop_event_ser.is_set():

            #Modo de Prueba
            if self.modo_prueba:
                vals = []
                muestras_por_ciclo = int(self.frecuenciaSenal * 0.02)  
                for _ in range(muestras_por_ciclo):
                    self.tri_val += self.tri_step * self.tri_dir
                    if self.tri_val >= self.tri_max:
                        self.tri_val = self.tri_max
                        self.tri_dir = -1
                    elif self.tri_val <= self.tri_min:
                        self.tri_val = self.tri_min
                        self.tri_dir = 1
                    vals.append(self.tri_val)
                now = time.time()
                with self.buf_lock:
                    vals = np.array(vals, dtype=float)
                    self.ruido = np.zeros(len(vals))
                    if self.gaussiano:
                        self.ruido = np.random.normal(0.0, 10.0, size=len(vals))
                    if self.impulso:
                        prob = 0.05  # 5% de los valores tendrán impulso
                        for i in range(len(vals)):
                            if np.random.rand() < prob:
                                self.ruido[i] = np.max(vals) if np.random.rand() < 0.5 else np.min(vals)
                    if self.artefacto:
                        self.ruido = np.zeros(len(vals))
                        n_art = 1  # número de artefactos
                        dur = 1     # duración de cada artefacto en puntos
                        for _ in range(n_art):
                            start = np.random.randint(0, len(vals) - dur)
                            incremento = np.random.uniform(50, 100)  # valor del artefacto
                            self.ruido[start:start+dur] += incremento
                    self.potenciaRuido = np.mean(self.ruido**2)
                    vals += self.ruido
                    for v in vals:  
                        v -= self.offset
                        self.buffer1.append(v)
                        self.buffer2.append(now)
                        now += 1.0 / self.frecuenciaSenal
                time.sleep(0.02)
                continue

            
            #Modo normal
            if self.ser is not None and self.ser.is_open:
                try:
                    n = self.ser.in_waiting #cantidad de datos que le llegan

                    #Espera a que le lleguen dos
                    if n >= 2:
                        raw = self.ser.read(n) #lee lo que le lleguen

                        #si los datos que le llegan son impares, lee uno mas para completar una cantidad par
                        if len(raw) % 2 == 1:
                            raw += self.ser.read(1)

                        #traduce las parejas de datos en un valor real en mV
                        vals = []
                        for j in range(0, len(raw), 2):
                            hi = raw[j]
                            lo = raw[j+1]
                            value = (hi * 100) + lo
                            vals.append(value)

                        now = time.time()

                        with self.buf_lock: #el buf_lock es para que los vectores no se corrompan cuando se accede a ellos de diferentes lugares al mismo tiempo

                            vals = np.array(vals, dtype=float)
                            self.ruido = np.zeros(len(vals))

                            if self.gaussiano:
                                self.ruido = np.random.normal(0.0, 50.0, size=len(vals)) #crea ruido random con una semilla normal

                            if self.impulso:
                                prob = 0.05  # porcentaje con ruido
                                for i in range(len(vals)):
                                    if np.random.rand() < prob:
                                        self.ruido[i] = np.max(vals) if np.random.rand() < 0.5 else np.min(vals) #les da un valor maximo 

                            if self.artefacto:
                                self.ruido = np.zeros(len(vals))
                                n_art = 1  # número de artefactos
                                dur = 1     # duración de cada artefacto en puntos
                                for _ in range(n_art):
                                    start = np.random.randint(0, len(vals) - dur)
                                    incremento = np.random.uniform(50, 100)  #artefacto
                                    self.ruido[start:start+dur] += incremento

                            vals += self.ruido

                            for v in vals:
                                v -= self.offset
                                self.buffer1.append(v)
                                self.buffer2.append(now)
                                now += 1.0 / self.frecuenciaSenal

                    else:
                        time.sleep(0.005) #espera 5ms antes de volver a ejecutar el hilo

                except Exception as e:
                    print("Error en hilo serial:", e)

# Main, para hacer llamado a la funcion principal
if __name__=="__main__":
    app= QApplication(sys.argv)
    ventana = principal()
    ventana.show()
    sys.exit(app.exec())




import sys, threading, time
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import QTimer, Qt, QEvent, pyqtSignal
from PyQt5.QtGui import QFont
import RPi.GPIO as GPIO


class MarcadorHandball(QWidget):
    # --- señales que ejecutarán acciones en el hilo principal ---
    signal_boton = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # --- Estado inicial ---
        self.goles_local = 0
        self.goles_visitante = 0
        self.tiempo = 0
        self.contando = False
        self.descendente = False
        self.periodo = 0
        self.periodos = ["1er Tiempo", "2do Tiempo", "1ra Prórroga", "2da Prórroga", "Penales"]

        # --- Configurar keypad ---
        self.filas = [17, 27, 22, 23]
        self.columnas = [24, 25, 5, 6]
        self.setup_keypad()

        self.initUI()

        # Conectar la señal con el método que procesa el botón
        self.signal_boton.connect(self.procesar_boton)

        # --- Iniciar hilo de lectura de botones ---
        hilo = threading.Thread(target=self.leer_teclado, daemon=True)
        hilo.start()

    # ---------- HARDWARE ----------
    def setup_keypad(self):
        GPIO.setmode(GPIO.BCM)
        for c in self.columnas:
            GPIO.setup(c, GPIO.OUT)
            GPIO.output(c, GPIO.HIGH)
        for r in self.filas:
            GPIO.setup(r, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.teclas = [
            ["S1", "S2", "S3", "S4"],
            ["S5", "S6", "S7", "S8"],
            ["S9", "S10", "S11", "S12"],
            ["S13", "S14", "S15", "S16"]
        ]

    def leer_teclado(self):
        while True:
            for c, col_pin in enumerate(self.columnas):
                GPIO.output(col_pin, GPIO.LOW)
                for r, row_pin in enumerate(self.filas):
                    if GPIO.input(row_pin) == 0:
                        tecla = self.teclas[r][c]
                        # En vez de llamar directo ? emitimos la señal
                        self.signal_boton.emit(tecla)
                        while GPIO.input(row_pin) == 0:
                            time.sleep(0.05)
                GPIO.output(col_pin, GPIO.HIGH)
            time.sleep(0.05)

    # ---------- ACCIONES ----------
    def procesar_boton(self, tecla):
        if tecla == "S1":
            self.add_gol("local")
        elif tecla == "S2":
            self.add_gol("local", restar=True)
        elif tecla == "S3":
            self.add_gol("visitante")
        elif tecla == "S4":
            self.add_gol("visitante", restar=True)
        elif tecla == "S5":
            self.iniciar_timer()
        elif tecla == "S6":
            self.pausar_timer()
        elif tecla == "S7":
            self.toggle_modo()
        elif tecla == "S8":
            self.cambiar_periodo()
        elif tecla == "S9":
            self.reset()

    # ---------- INTERFAZ ----------
    def initUI(self):
        self.setWindowTitle("Marcador Handball")
        self.setStyleSheet("background-color: black; color: white;")

        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)

        grid = QGridLayout()
        grid.setHorizontalSpacing(40)
        grid.setVerticalSpacing(20)

        self.lbl_local = QLabel("Local: 0")
        self.lbl_visit = QLabel("Visitante: 0")
        for lbl in [self.lbl_local, self.lbl_visit]:
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        grid.addWidget(self.lbl_local, 0, 0)
        grid.addWidget(self.lbl_visit, 1, 0)
        layout.addLayout(grid)

        # Periodo
        self.lbl_periodo = QLabel(self.periodos[self.periodo])
        self.lbl_periodo.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_periodo)

        # Tiempo e indicadores
        self.lbl_tiempo = QLabel("00:00")
        self.lbl_tiempo.setAlignment(Qt.AlignCenter)
        self.lbl_estado = QLabel("Pausado")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_modo = QLabel("Modo: ASCENDENTE")
        self.lbl_modo.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.lbl_tiempo)
        layout.addWidget(self.lbl_estado)
        layout.addWidget(self.lbl_modo)

        # Botones GUI
        btn_iniciar = QPushButton("Iniciar")
        btn_iniciar.clicked.connect(self.iniciar_timer)
        btn_pausar = QPushButton("Pausar")
        btn_pausar.clicked.connect(self.pausar_timer)
        btn_toggle = QPushButton("Tiempo Asc/Des")
        btn_toggle.clicked.connect(self.toggle_modo)
        btn_reset = QPushButton("Terminar Partido")
        btn_reset.clicked.connect(self.reset)

        fila_botones = QHBoxLayout()
        fila_botones.addWidget(btn_iniciar)
        fila_botones.addWidget(btn_pausar)
        fila_botones.addWidget(btn_toggle)
        fila_botones.addWidget(btn_reset)
        layout.addLayout(fila_botones)

        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.actualizar_tiempo)

        self.installEventFilter(self)

    # ---------- ESCALADO ----------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.adjust_font_sizes()
        return super().eventFilter(obj, event)

    def adjust_font_sizes(self):
        base = int(self.height() / 18)
        for lbl in self.findChildren(QLabel):
            lbl.setFont(QFont("Arial", base))
        for btn in self.findChildren(QPushButton):
            btn.setFont(QFont("Arial", base * 0.8))

    # ---------- LÓGICA ----------
    def add_gol(self, equipo, restar=False):
        if equipo == "local":
            self.goles_local = max(0, self.goles_local - 1) if restar else self.goles_local + 1
            self.lbl_local.setText(f"Local: {self.goles_local}")
        else:
            self.goles_visitante = max(0, self.goles_visitante - 1) if restar else self.goles_visitante + 1
            self.lbl_visit.setText(f"Visitante: {self.goles_visitante}")

    def iniciar_timer(self):
        # Si el cronómetro estaba finalizado, reiniciamos al valor inicial correcto
        if self.lbl_estado.text() == "Finalizado":
            if self.descendente:
                self.tiempo = 1800  # 30 minutos descendente
            else:
                self.tiempo = 0  # 0 en modo ascendente

            # Actualizar visualmente el tiempo reseteado
            minutos = self.tiempo // 60
            segundos = self.tiempo % 60
            self.lbl_tiempo.setText(f"{minutos:02}:{segundos:02}")

        # Iniciar si no está contando
        if not self.contando:
            self.timer.start(1000)
            self.contando = True
            self.lbl_estado.setText("Contando...")

    def pausar_timer(self):
        if self.contando:
            self.timer.stop()
            self.contando = False
            self.lbl_estado.setText("Pausado")

    def toggle_modo(self):
        self.descendente = not self.descendente
        self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
        if self.descendente:
            self.tiempo = 1800
            self.lbl_tiempo.setText("30:00")

    def cambiar_periodo(self):
        self.periodo = (self.periodo + 1) % len(self.periodos)
        self.lbl_periodo.setText(self.periodos[self.periodo])


    def actualizar_tiempo(self):
        if self.descendente:
            # --- Cuenta regresiva ---
            if self.tiempo <= 0:
                self.tiempo = 0
                self.pausar_timer()
                self.lbl_estado.setText("Finalizado")
                self.lbl_tiempo.setText("00:00")
                return
            self.tiempo -= 1
        else:
            # --- Cuenta ascendente ---
            if self.tiempo >= 1800:  # 30 minutos
                self.tiempo = 1800
                self.pausar_timer()
                self.lbl_estado.setText("Finalizado")
                self.lbl_tiempo.setText("30:00")
                return
            self.tiempo += 1

        minutos = self.tiempo // 60
        segundos = self.tiempo % 60
        self.lbl_tiempo.setText(f"{minutos:02}:{segundos:02}")


    def reset(self):
        self.goles_local = 0
        self.goles_visitante = 0
        self.tiempo = 0 if not self.descendente else 1800
        self.lbl_local.setText("Local: 0")
        self.lbl_visit.setText("Visitante: 0")
        self.lbl_tiempo.setText("00:00" if not self.descendente else "30:00")
        self.lbl_periodo.setText(self.periodos[0])
        self.lbl_estado.setText("Pausado")
        self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
        self.timer.stop()
        self.contando = False
        self.periodo = 0

    def closeEvent(self, event):
        GPIO.cleanup()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MarcadorHandball()
    win.showMaximized()
    sys.exit(app.exec_())

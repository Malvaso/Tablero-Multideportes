#!/usr/bin/env python3
import sys
import threading
import time
import json
import os

# descomentar todos los #self.guardar_estado()

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QSizePolicy, QFrame
)
from PyQt5.QtCore import QTimer, Qt, QEvent, pyqtSignal
from PyQt5.QtGui import QFont, QCursor

# IMPORT GPIO (asume ejecución en Raspberry)
import RPi.GPIO as GPIO

# ---------------------------------------------------------
# handball7.py - marcador de handball con menú y penales
# ---------------------------------------------------------
# Hardware mapping (matriz 4x4 keypad)
# Filas (inputs): GPIO 17,27,22,23
# Columnas (outputs): GPIO 24,25,5,6
#
# Teclas mapeadas (según tu diseño):
#  S1 S2 S3 S4  -> primera fila del keypad (R1)
#  S5 S6 S7 S8  -> segunda fila (R2)
#  S9 S10 S11 S12 -> tercera fila (R3)
#  S13 S14 S15 S16 -> cuarta fila (R4)
#
# Nosotros interpretamos:
# - S1: Gol Local +       (teclas[0][0])
# - S2: Gol Local -       (teclas[0][1])
# - S3: Gol Visitante +   (teclas[0][2])
# - S4: Gol Visitante -   (teclas[0][3])
# - S5: Iniciar tiempo    (teclas[1][0])
# - S6: Pausar tiempo     (teclas[1][1])
# - S7: (sin uso)         (teclas[1][2])
# - S8: Cambiar período   (teclas[1][3])
# - S9: Reset             (teclas[2][0])
# - S10: Back             (teclas[2][1])
# - S11: Up               (teclas[2][2])
# - S12: Enter            (teclas[2][3])
# - S13: Config (toggle)  (teclas[3][0])
# - S14: Left             (teclas[3][1])
# - S15: Down             (teclas[3][2])
# - S16: Right            (teclas[3][3])
#
# Ajustá si tu keypad tiene otra disposición física.
# ---------------------------------------------------------

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

class MarcadorHandball(QWidget):
    signal_boton = pyqtSignal(str)

    ARCHIVO_ESTADO = "/home/ariel/Desktop/TableroMultideportes/estado_tablero.json"

    def __init__(self):
        super().__init__()

        # Estado básico
        self.goles_local = 0
        self.goles_visitante = 0
        self.tiempo = 0
        self.contando = False
        self.descendente = False
        # Tiempo inicial configurado (por defecto 30 min = 1800 segundos)
        self.tiempo_inicial = 0
        self.editando_digito = 0  # 0=minuto1,1=minuto2,2=segundo1,3=segundo2
        self.editando_tiempo = False
        self.digito_tiempo = 0  # 0-3 pos: M1 M2 S1 S2
        self.periodo = 0
        self.periodos = ["1er Tiempo", "2do Tiempo", "1ra Prórroga", "2da Prórroga", "Penales"]

        # Penales
        self.penales_activo = False
        self.penales_local = ["-"] * 5
        self.penales_visitante = ["-"] * 5
        self.historial_penales = []  # lista de tuples ("L"|"V", index)
        self.ganador = None  # "L" o "V" o None

        # Menú
        self.menu_activo = False
        # items: each entry is (label_prefix, possible values or None)
        self.menu_items = [
            ("Tiempo", ["ASCENDENTE", "DESCENDENTE"]),
            ("Penales", ["OFF", "ON"]),
            ("Tiempo Inicial", None)
        ]
        self.menu_index = 0  # selected item
        # For Tiempo, index 0 => ASCENDENTE, 1 => DESCENDENTE; for Penales, 0=>OFF,1=>ON

        # Keypad pins
        self.filas = [17, 27, 22, 23]
        self.columnas = [24, 25, 5, 6]
        self.teclas = [
            ["S1", "S2", "S3", "S4"],
            ["S5", "S6", "S7", "S8"],
            ["S9", "S10", "S11", "S12"],
            ["S13", "S14", "S15", "S16"]
        ]

        # Setup hardware and UI
        self.setup_keypad()
        self.initUI()
        self.cargar_estado()

        # connect signal and start keypad thread
        self.signal_boton.connect(self.procesar_boton)
        hilo = threading.Thread(target=self.leer_teclado, daemon=True)
        hilo.start()

        # timer de guardado cada 60s si está contando
        self.timer_guardado = QTimer()
        self.timer_guardado.timeout.connect(self.guardar_si_contando)
        self.timer_guardado.start(60000)  # 60s

        # move cursor away
        try:
            QCursor.setPos(6000, -1000)
        except:
            pass


    # ----------------------------
    # Persistencia
    # ----------------------------
    def guardar_estado(self):
        estado = {
            "goles_local": self.goles_local,
            "goles_visitante": self.goles_visitante,
            "tiempo": self.tiempo,
            "periodo": self.periodo,
            "descendente": self.descendente,
            "penales_activo": self.penales_activo,
            "penales_local": self.penales_local,
            "penales_visitante": self.penales_visitante
        }
        try:
            with open(self.ARCHIVO_ESTADO, "w") as f:
                json.dump(estado, f)
        except Exception as e:
            print("Error guardando estado:", e)
            
            
    def cargar_estado(self):
    
        #Carga el estado desde ARCHIVO_ESTADO y reconstruye la UI de penales
        #respetando columnas de muerte súbita (listas de longitud arbitraria).
        #También recalcula ganador y actualiza la visualización.
    
        # valores por defecto en caso de no existir archivo o error
        estado = None
        if os.path.exists(self.ARCHIVO_ESTADO):
            try:
                with open(self.ARCHIVO_ESTADO, "r") as f:
                    estado = json.load(f)
            except Exception as e:
                print("Error cargando estado desde JSON:", e)
                estado = None

        if estado:
            try:
                self.goles_local = int(estado.get("goles_local", 0))
                self.goles_visitante = int(estado.get("goles_visitante", 0))
                self.tiempo = int(estado.get("tiempo", 0))
                self.periodo = int(estado.get("periodo", 0))
                self.descendente = bool(estado.get("descendente", False))
                self.penales_activo = bool(estado.get("penales_activo", False))

                # Cargar listas de penales (pueden tener más de 5 en muerte súbita)
                penales_local = estado.get("penales_local", ["-"] * 5)
                penales_visit = estado.get("penales_visitante", ["-"] * 5)

                # garantizar que ambas listas tengan la misma longitud
                maxlen = max(len(penales_local), len(penales_visit))
                if len(penales_local) < maxlen:
                    penales_local = penales_local + ["-"] * (maxlen - len(penales_local))
                if len(penales_visit) < maxlen:
                    penales_visit = penales_visit + ["-"] * (maxlen - len(penales_visit))

                self.penales_local = penales_local
                self.penales_visitante = penales_visit

            except Exception as e:
                print("Error aplicando campos del estado:", e)
                # mantener valores por defecto en caso de problemas
        else:
            # No hay estado guardado: mantener defaults
            self.penales_local = ["-"] * 5
            self.penales_visitante = ["-"] * 5

        # -----------------------
        # (Re)construir widgets de penales según las listas cargadas
        # -----------------------
        try:
            # Limpiar widgets anteriores
            for lbl in getattr(self, "penales_local_labels", []) + getattr(self, "penales_visit_labels", []):
                try:
                    lbl.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass

        self.penales_local_labels = []
        self.penales_visit_labels = []

        # Asegurar que row_local / row_visit existen (normalmente creados en initUI)
        if not hasattr(self, "row_local") or not hasattr(self, "row_visit"):
            try:
                lf = self.penales_frame.layout()
                # asumimos estructura: 0:title, 1:row_local, 2:row_visit
                self.row_local = lf.itemAt(1).layout()
                self.row_visit = lf.itemAt(2).layout()
            except Exception:
                # crear layouts si algo raro pasó
                self.row_local = QHBoxLayout()
                self.row_visit = QHBoxLayout()
                self.penales_frame.layout().addLayout(self.row_local)
                self.penales_frame.layout().addLayout(self.row_visit)

        # Construir labels según la longitud actual de las listas
        base_now = max(10, int(self.height() / 18))
        font_sym = QFont("Arial", int(base_now * 1.4))
        label_font = QFont("Arial", int(base_now * 1.0))

        for i in range(len(self.penales_local)):
            # local label
            a = QLabel(self.penales_local[i] if i < len(self.penales_local) else "-")
            a.setAlignment(Qt.AlignCenter)
            a.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            a.setFont(font_sym)
            self.penales_local_labels.append(a)
            self.row_local.addWidget(a)

        for i in range(len(self.penales_visitante)):
            # visitante label
            b = QLabel(self.penales_visitante[i] if i < len(self.penales_visitante) else "-")
            b.setAlignment(Qt.AlignCenter)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            b.setFont(font_sym)
            self.penales_visit_labels.append(b)
            self.row_visit.addWidget(b)

        # Asegurar que etiquetas "L:" y "V:" mantengan fuente consistente
        if hasattr(self, "lbl_penales_L"):
            self.lbl_penales_L.setFont(label_font)
        if hasattr(self, "lbl_penales_V"):
            self.lbl_penales_V.setFont(label_font)

        # -----------------------
        # Re-evaluar ganador y UI
        # -----------------------
        try:
            # recalcular ganador a partir del estado cargado
            self.chequear_ganador()
        except Exception as e:
            print("Error al chequear ganador tras cargar estado:", e)

        # Ajustar tamaños y actualizar la vista completa
        try:
            self.adjust_font_sizes()
        except Exception:
            pass

        # Visibilidad del panel de penales según estado
        if getattr(self, "penales_activo", False):
            self.penales_frame.setVisible(True)
            self.lbl_tiempo.setVisible(False)
            self.lbl_estado.setVisible(False)
            self.lbl_periodo.setVisible(False)
            self.lbl_modo.setVisible(False)
        else:
            self.penales_frame.setVisible(False)
            self.lbl_tiempo.setVisible(True)
            self.lbl_estado.setVisible(True)
            self.lbl_periodo.setVisible(True)
            self.lbl_modo.setVisible(True)

        # Finalmente, actualizar resto de la UI (scores, periodo, modo, menú)
        try:
            self.lbl_local_score.setText(str(self.goles_local))
            self.lbl_visit_score.setText(str(self.goles_visitante))
            self.lbl_periodo.setText(self.periodos[self.periodo])
            self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
            # tiempo mostrado según valor actual
            if not self.penales_activo:
                self.lbl_tiempo.setText(self._format_time(self.tiempo))
            self.lbl_estado.setText("Contando..." if self.contando else "Pausado")
            self.actualizar_penales_ui()
            self.render_menu()
        except Exception:
            pass
            
    """
    def cargar_estado(self):
        if os.path.exists(self.ARCHIVO_ESTADO):
            try:
                with open(self.ARCHIVO_ESTADO, "r") as f:
                    estado = json.load(f)
                self.goles_local = int(estado.get("goles_local", 0))
                self.goles_visitante = int(estado.get("goles_visitante", 0))
                self.tiempo = int(estado.get("tiempo", 0))
                self.periodo = int(estado.get("periodo", 0))
                self.descendente = bool(estado.get("descendente", False))
                self.penales_activo = bool(estado.get("penales_activo", False))
                self.penales_local = estado.get("penales_local", ["-"]*5)
                self.penales_visitante = estado.get("penales_visitante", ["-"]*5)
            except Exception as e:
                print("Error cargando estado:", e)

        # Aplicar visual
        self.actualizar_ui_completa(startup=True)
    """
    def guardar_si_contando(self):
        if self.contando:
            self.guardar_estado()

    # ----------------------------
    # Keypad hardware
    # ----------------------------
    def setup_keypad(self):
        # columnas como outputs; filas como inputs con pullups
        for c in self.columnas:
            GPIO.setup(c, GPIO.OUT)
            GPIO.output(c, GPIO.HIGH)
        for r in self.filas:
            GPIO.setup(r, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def leer_teclado(self):
        # simple scanning; emite señal (GUI thread) para procesar
        while True:
            for c, col_pin in enumerate(self.columnas):
                GPIO.output(col_pin, GPIO.LOW)
                for r, row_pin in enumerate(self.filas):
                    if GPIO.input(row_pin) == 0:
                        tecla = self.teclas[r][c]
                        self.signal_boton.emit(tecla)
                        # debounce: esperar hasta que suelte
                        while GPIO.input(row_pin) == 0:
                            time.sleep(0.05)
                GPIO.output(col_pin, GPIO.HIGH)
            time.sleep(0.02)

    # ----------------------------
    # Procesado de botones (hilo GUI)
    # ----------------------------
    def procesar_boton(self, tecla):
        # --- si estoy editando el tiempo inicial, manejar teclas ahí ---
        if getattr(self, "editando_tiempo", False):
            # procesar solo las flechas y enter/back
            if tecla in ("S11", "S15", "S14", "S16"):
                self.editar_tiempo_handler(tecla)
                return
            if tecla == "S12":  # Enter confirma edición
                self.editando_tiempo = False
                # al confirmar, aplico el tiempo inicial al cronómetro (pausado)
                self.tiempo = int(self.tiempo_inicial)
                # actualizar visual grande (sin resaltado)
                self.update_time_label_plain()
                self.render_menu()
                #self.guardar_estado()
                return
            if tecla == "S10":  # Back cancela edición (vuelve sin guardar)
                self.editando_tiempo = False
                self.update_time_label_plain()
                self.render_menu()
                return

        # navegación del menú y acciones; todos los botones deben funcionar aún si el menú está abierto
        # Mapeo de acciones:
        if tecla == "S1":  # Gol local +
            if self.penales_activo:
                self.marcar_penal_local("O")
            else:
                self.add_gol("local")
        elif tecla == "S2":  # Gol local -
            if self.penales_activo:
                self.marcar_penal_local("X")
            else:
                self.add_gol("local", restar=True)
        elif tecla == "S3":  # Gol visitante +
            if self.penales_activo:
                self.marcar_penal_visitante("O")
            else:
                self.add_gol("visitante")
        elif tecla == "S4":  # Gol visitante -
            if self.penales_activo:
                self.marcar_penal_visitante("X")
            else:
                self.add_gol("visitante", restar=True)
        elif tecla == "S5":
            self.iniciar_timer()
        elif tecla == "S6":
            self.pausar_timer()
        elif tecla == "S8":
            # cambiar periodo funciona aun con menu
            if not self.penales_activo:
                self.cambiar_periodo()
        elif tecla == "S9":
            # reset: comportamiento distinto según modo
            if self.penales_activo:
                self.reset_penales()
            else:
                self.reset_total()
        elif tecla == "S13":  # toggle menu
            self.toggle_menu()
        elif tecla == "S10":  # back
            self.menu_back()
        elif tecla == "S11":  # up
            self.menu_up()
        elif tecla == "S15":  # down
            self.menu_down()
        elif tecla == "S14":  # left
            self.menu_left()
        elif tecla == "S16":  # right
            self.menu_right()
        elif tecla == "S12":  # enter
            self.menu_enter()

    # ----------------------------
    # UI
    # ----------------------------
    def initUI(self):
        self.setWindowTitle("Marcador Handball")
        self.setStyleSheet("background-color: black; color: white;")
        self.layout_principal = QVBoxLayout()
        self.layout_principal.setContentsMargins(20, 20, 20, 20)

        # --- Score line (single row) ---
        score_layout = QHBoxLayout()
        score_layout.setSpacing(20)

        self.lbl_local_txt = QLabel("LOCAL")
        self.lbl_local_score = QLabel("0")
        self.lbl_guion = QLabel("-")
        self.lbl_visit_score = QLabel("0")
        self.lbl_visit_txt = QLabel("VISITANTE")

        for lbl in [self.lbl_local_txt, self.lbl_local_score, self.lbl_guion,
                    self.lbl_visit_score, self.lbl_visit_txt]:
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # make score numbers bigger via font in adjust_font_sizes
        score_layout.addWidget(self.lbl_local_txt)
        score_layout.addWidget(self.lbl_local_score)
        score_layout.addWidget(self.lbl_guion)
        score_layout.addWidget(self.lbl_visit_score)
        score_layout.addWidget(self.lbl_visit_txt)
        self.layout_principal.addLayout(score_layout)

        # Period label
        self.lbl_periodo = QLabel(self.periodos[self.periodo])
        self.lbl_periodo.setAlignment(Qt.AlignCenter)
        self.layout_principal.addWidget(self.lbl_periodo)

        # Tiempo e indicadores (tiempo se oculta en penales)
        self.lbl_tiempo = QLabel("00:00")
        self.lbl_tiempo.setAlignment(Qt.AlignCenter)
        self.lbl_estado = QLabel("Pausado")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_modo = QLabel("Modo: ASCENDENTE")
        self.lbl_modo.setAlignment(Qt.AlignCenter)

        self.layout_principal.addWidget(self.lbl_tiempo)
        self.layout_principal.addWidget(self.lbl_estado)
        self.layout_principal.addWidget(self.lbl_modo)

        # Panel para penales (oculto hasta activación)
        self.penales_frame = QFrame()
        penales_layout_v = QVBoxLayout()
        self.penales_lbl_title = QLabel("PENALES")
        self.penales_lbl_title.setAlignment(Qt.AlignCenter)
        penales_layout_v.addWidget(self.penales_lbl_title)

        # filas de penales: local y visitante
        self.penales_local_labels = []
        self.penales_visit_labels = []
        
        self.row_local = QHBoxLayout()
        self.row_visit = QHBoxLayout()
        self.row_local.setSpacing(10)
        self.row_visit.setSpacing(10)
        
        self.lbl_penales_L = QLabel("L:")
        self.lbl_penales_V = QLabel("V:")
        self.lbl_penales_L.setAlignment(Qt.AlignCenter)
        self.lbl_penales_V.setAlignment(Qt.AlignCenter)
        self.row_local.addWidget(self.lbl_penales_L)
        self.row_visit.addWidget(self.lbl_penales_V)
        

        for i in range(5):
            a = QLabel(self.penales_local[i])
            b = QLabel(self.penales_visitante[i])
            a.setAlignment(Qt.AlignCenter)
            b.setAlignment(Qt.AlignCenter)
            a.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.penales_local_labels.append(a)
            self.penales_visit_labels.append(b)
            self.row_local.addWidget(a)
            self.row_visit.addWidget(b)

        penales_layout_v.addLayout(self.row_local)
        penales_layout_v.addLayout(self.row_visit)
        self.penales_frame.setLayout(penales_layout_v)
        self.penales_frame.setVisible(False)
        self.layout_principal.addWidget(self.penales_frame)

        # ---------- MENÚ (aparece abajo, no tapa la información) ----------
        self.menu_frame = QFrame()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.menu_frame.setFrameShape(QFrame.StyledPanel)
        #self.menu_frame.setStyleSheet("background-color: rgba(30,30,30,230);")
        self.menu_frame.setStyleSheet("""
        background-color: rgba(30,30,30,230);
        border: 2px solid gray;
        """)
        menu_layout = QVBoxLayout()
        menu_layout.setContentsMargins(8, 8, 8, 8)
        menu_layout.setSpacing(6)  # separa los items uno debajo del otro
        self.menu_labels = []
        for i, (name, values) in enumerate(self.menu_items):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignLeft)  # mejor alineado para lista vertical
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lbl.setMinimumHeight(40)  # <- evita que se corten al achicar
            self.menu_labels.append(lbl)
            menu_layout.addWidget(lbl)
        self.menu_frame.setLayout(menu_layout)
        self.menu_frame.setContentsMargins(10, 5, 10, 5)  # margen interno
        
        self.menu_frame.setVisible(False)
        self.layout_principal.addWidget(self.menu_frame)

        self.setLayout(self.layout_principal)

        # Timer de 1s para cronómetro
        self.timer = QTimer()
        self.timer.timeout.connect(self.actualizar_tiempo)

        # ajustar fuentes cuando cambia tamaño
        self.installEventFilter(self)
        self.menu_frame.setFixedHeight(int(self.height() * 0.15))


    # ----------------------------
    # Menú: navegación y render
    # ----------------------------
    def toggle_menu(self):
        # toggle show/hide menu. Menu can be opened while penales active (but doesn't affect penales UI)
        self.menu_activo = not self.menu_activo
        self.menu_frame.setVisible(self.menu_activo)
        # si abrimos el menú en penales, aseguramos que el fondo y texto sean legibles
        if self.menu_activo:
            for lbl in self.menu_labels:
                lbl.setStyleSheet("color: white; background: transparent;")
        # always refresh labels
        self.render_menu()

    def menu_back(self):
        # Si estamos en penales: BACK borra último penal (undo)
        if self.penales_activo:
            if not self.historial_penales:
                return  # A: ignorar si no hay nada
            ultimo, idx = self.historial_penales.pop()
            if ultimo == "L":
                # volver el símbolo a '-'
                if idx < len(self.penales_local):
                    self.penales_local[idx] = "-"
                    self.penales_local_labels[idx].setText("-")
            else:
                if idx < len(self.penales_visitante):
                    self.penales_visitante[idx] = "-"
                    self.penales_visit_labels[idx].setText("-")
            # si había ganador, re-evaluar
            self.ganador = None
            self.chequear_ganador()
            return

        # si no estamos en penales, el back cierra el menú como antes
        if self.menu_activo:
            self.menu_activo = False
            self.menu_frame.setVisible(False)
            
        self.actualizar_penales_ui()

    def menu_up(self):
        if not self.menu_activo:
            return
        self.menu_index = (self.menu_index - 1) % len(self.menu_items)
        self.render_menu()

    def menu_down(self):
        if not self.menu_activo:
            return
        self.menu_index = (self.menu_index + 1) % len(self.menu_items)
        self.render_menu()

    def menu_left(self):
        if not self.menu_activo:
            return
        name, values = self.menu_items[self.menu_index]
        if values is None:
            return

        if name == "Tiempo":
            # toggle asc/desc
            self.descendente = not self.descendente
            self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
            # no visual effect in penales, pero guardamos
            #self.guardar_estado()
        elif name == "Penales":
            # toggle penales on/off
            prev = self.penales_activo
            self.penales_activo = not prev

            if self.penales_activo:
                # entrar en penales: cerrar menu, ocultar tiempo y periodo, mostrar panel penales
                self.menu_activo = False
                self.menu_frame.setVisible(False)
                # ocultar tiempo y periodo y estado
                self.lbl_tiempo.setVisible(False)
                self.lbl_estado.setVisible(False)
                self.lbl_periodo.setVisible(False)
                self.lbl_modo.setVisible(False)
                # pausar timer por seguridad
                if self.contando:
                    self.pausar_timer()
                self.penales_frame.setVisible(True)
            else:
                # salir de penales: restaurar visibilidad de tiempo y periodo
                self.penales_frame.setVisible(False)
                self.lbl_tiempo.setVisible(True)
                self.lbl_estado.setVisible(True)
                self.lbl_periodo.setVisible(True)
                self.lbl_modo.setVisible(True)
            # guardar el estado
            #self.guardar_estado()

        # actualizar menu labels si sigue abierto
        self.render_menu()
        
    def menu_right(self):
        # same as left (toggle)
        self.menu_left()

    def menu_enter(self):
        # Si estamos editando, Enter confirma -> handled en procesar_boton
        if self.editando_tiempo:
            return

        # Si no hay menú y estamos en periodo Penales: Enter activa modo penales (si corresponde)
        if not self.menu_activo and self.periodo == 4:
            if not self.penales_activo:
                self.penales_activo = True
                # no cambiamos self.periodo (lo pediste así)
                # ocultar tiempo si corresponde
                self.lbl_tiempo.setVisible(False)
                self.lbl_estado.setVisible(False)
                self.lbl_modo.setVisible(False)
                if self.contando:
                    self.pausar_timer()
                self.penales_frame.setVisible(True)
                self.render_menu()
            return

        if not self.menu_activo:
            return

        name, values = self.menu_items[self.menu_index]

        if name == "Tiempo Inicial":
            # entrar en modo edición
            self.editando_tiempo = True
            self.pausar_timer()
            # comenzar con el primer dígito seleccionado
            self.digito_tiempo = 0
            # mostrar el tiempo_inicial grande con el dígito amarillo
            self.update_time_label_with_highlight()
            self.render_menu()
        else:
            # default: toggle behavior
            self.menu_left()


    def render_menu(self):
        self.menu_frame.setStyleSheet("""
            background-color: rgba(30,30,30,240);
            border-top: 2px solid #666;
        """)

        for i, (name, values) in enumerate(self.menu_items):

            if name == "Tiempo":
                val = "DESCENDENTE" if self.descendente else "ASCENDENTE"

            elif name == "Penales":
                val = "ON" if self.penales_activo else "OFF"

            elif name == "Tiempo Inicial":
                secs = self.tiempo_inicial
                m = secs // 60
                s = secs % 60
                digits = f"{m:02d}:{s:02d}"
                if self.editando_tiempo:
                    pos = self.digito_tiempo
                    idx = [0,1,3,4][pos]  # mapping en string
                    digits = (
                        digits[:idx] +
                        f"<span style='color:yellow;'>{digits[idx]}</span>" +
                        digits[idx+1:]
                    )
                val = digits

            else:
                val = ""

            texto = f"{name}: {val}"

            if i == self.menu_index:
                self.menu_labels[i].setText(f"> {texto}")
                self.menu_labels[i].setStyleSheet("color: yellow;")
            else:
                self.menu_labels[i].setText(f"  {texto}")
                self.menu_labels[i].setStyleSheet("color: white;")
    
    
    # ----------------------------
    # Penales handling
    # ----------------------------
    
    def marcar_penal_local(self, symbol):
        # Si ya hubo ganador -> no dejar seguir
        if self.ganador:
            return

        self.ganador = None

        # Buscar primer espacio libre existente
        for i in range(len(self.penales_local)):
            if self.penales_local[i] == "-":
                self.penales_local[i] = symbol
                self.penales_local_labels[i].setText(symbol)
                self.historial_penales.append(("L", i))
                self.adjust_font_sizes()
                self.chequear_ganador()
                self.actualizar_penales_ui()
                #self.guardar_estado()
                return

		# Si no hay lugar - muerte súbita: crear nueva columna (Local primero)
        self.penales_local.append(symbol)
        a = QLabel(symbol)
        a.setAlignment(Qt.AlignCenter)
        a.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.penales_local_labels.append(a)
        self.row_local.addWidget(a)

        self.penales_visitante.append("-")
        b = QLabel("-")
        b.setAlignment(Qt.AlignCenter)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.penales_visit_labels.append(b)
        self.row_visit.addWidget(b)

        idx = len(self.penales_local) - 1
        self.historial_penales.append(("L", idx))
        self.adjust_font_sizes()
        self.chequear_ganador()
        self.actualizar_penales_ui()
        #self.guardar_estado()

    def marcar_penal_visitante(self, symbol):
        if self.ganador:
            return

        self.ganador = None

        for i in range(len(self.penales_visitante)):
            if self.penales_visitante[i] == "-":
                self.penales_visitante[i] = symbol
                self.penales_visit_labels[i].setText(symbol)
                self.historial_penales.append(("V", i))
                self.adjust_font_sizes()
                self.chequear_ganador()
                self.actualizar_penales_ui()
                #self.guardar_estado()
                return

        # Muerte súbita: visitante primero
        self.penales_visitante.append(symbol)
        b = QLabel(symbol)
        b.setAlignment(Qt.AlignCenter)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.penales_visit_labels.append(b)
        self.row_visit.addWidget(b)

        self.penales_local.append("-")
        a = QLabel("-")
        a.setAlignment(Qt.AlignCenter)
        a.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.penales_local_labels.append(a)
        self.row_local.addWidget(a)

        idx = len(self.penales_visitante) - 1
        self.historial_penales.append(("V", idx))
        self.adjust_font_sizes()
        self.chequear_ganador()
        self.actualizar_penales_ui()
        #self.guardar_estado()

    
    
    def reset_penales(self):
        
        #Reinicia la tanda de penales a 5 casillas por lado, restablece historial y
        #garantiza que los QLabel se creen con la fuente adecuada según el tamaño actual.
        
        # datos
        self.penales_local = ["-"] * 5
        self.penales_visitante = ["-"] * 5
        self.historial_penales = []
        self.ganador = None

        # eliminar widgets actuales de las filas y limpiar listas
        # asumimos que self.row_local y self.row_visit son QHBoxLayout usados en initUI()
        # y que penales_local_labels / penales_visit_labels contienen los QLabel actuales
        for lbl in self.penales_local_labels + self.penales_visit_labels:
            try:
                lbl.deleteLater()
            except:
                pass
        self.penales_local_labels.clear()
        self.penales_visit_labels.clear()

        # calcular fuente base acorde al tamaño actual
        base_now = max(10, int(self.height() / 18))
        penales_font = QFont("Arial", int(base_now * 1.4))
        label_font = QFont("Arial", int(base_now * 1.0))

        # si las filas no existen por algun motivo, intentar recuperarlas desde el layout
        if not hasattr(self, "row_local") or not hasattr(self, "row_visit"):
            # buscar en penales_frame: asumimos estructura [title, row_local_layout, row_visit_layout]
            try:
                lf = self.penales_frame.layout()
                self.row_local = lf.itemAt(1).layout()
                self.row_visit = lf.itemAt(2).layout()
            except:
                # si no se puede, crear nuevas
                self.row_local = QHBoxLayout()
                self.row_visit = QHBoxLayout()
                self.penales_frame.layout().addLayout(self.row_local)
                self.penales_frame.layout().addLayout(self.row_visit)

        # (re)construir 5 columnas base
        for i in range(5):
            a = QLabel(self.penales_local[i])
            a.setAlignment(Qt.AlignCenter)
            a.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            a.setFont(penales_font)

            b = QLabel(self.penales_visitante[i])
            b.setAlignment(Qt.AlignCenter)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            b.setFont(penales_font)

            self.penales_local_labels.append(a)
            self.penales_visit_labels.append(b)
            self.row_local.addWidget(a)
            self.row_visit.addWidget(b)

        # asegurar que el L: y V: también tengan fuente consistente
        if hasattr(self, "lbl_penales_L"):
            self.lbl_penales_L.setFont(label_font)
        if hasattr(self, "lbl_penales_V"):
            self.lbl_penales_V.setFont(label_font)

        # actualizar UI y persistir
        self.actualizar_penales_ui()
        """
        try: self.guardar_estado()
        except: pass
        """
    
    def actualizar_penales_ui(self):
        # actualiza textos de labels según las listas de datos
        for i in range(len(self.penales_local_labels)):
            if i < len(self.penales_local):
                self.penales_local_labels[i].setText(self.penales_local[i])
            else:
                self.penales_local_labels[i].setText("-")
        for i in range(len(self.penales_visit_labels)):
            if i < len(self.penales_visitante):
                self.penales_visit_labels[i].setText(self.penales_visitante[i])
            else:
                self.penales_visit_labels[i].setText("-")

        # aplicar color ganador en verde a L o V (según tu pedido)
        if self.ganador == "L":
            self.lbl_local_txt.setStyleSheet("color: lime;")
            self.lbl_visit_txt.setStyleSheet("color: white;")
        elif self.ganador == "V":
            self.lbl_visit_txt.setStyleSheet("color: lime;")
            self.lbl_local_txt.setStyleSheet("color: white;")
        else:
            self.lbl_local_txt.setStyleSheet("color: white;")
            self.lbl_visit_txt.setStyleSheet("color: white;")
            
    
    def chequear_ganador(self):
        primeros = 5

        # Conteo total y dentro de los 5 primeros
        golesL = sum(1 for s in self.penales_local if s == "O")
        golesV = sum(1 for s in self.penales_visitante if s == "O")

        tirosL = sum(1 for s in self.penales_local if s != "-")
        tirosV = sum(1 for s in self.penales_visitante if s != "-")

        golesL5 = sum(1 for s in self.penales_local[:primeros] if s == "O")
        golesV5 = sum(1 for s in self.penales_visitante[:primeros] if s == "O")
        tirosL5 = sum(1 for s in self.penales_local[:primeros] if s != "-")
        tirosV5 = sum(1 for s in self.penales_visitante[:primeros] if s != "-")

		# --- Fase inicial (5 tiros reglamentarios) ---
        restL = primeros - tirosL5
        restV = primeros - tirosV5

		# --- Eliminación matemática anticipada ---
        if golesL5 > golesV5 + restV:
            self.ganador = "L"
            self.actualizar_penales_ui()
            #self.guardar_estado()
            return
        if golesV5 > golesL5 + restL:
            self.ganador = "V"
            self.actualizar_penales_ui()
            #self.guardar_estado()
            return

        # --- Final de los 5 reglamentarios ---
        if tirosL5 == primeros and tirosV5 == primeros:
            if golesL5 > golesV5:
                self.ganador = "L"
                self.actualizar_penales_ui()
                #self.guardar_estado()
                return
            if golesV5 > golesL5:
                self.ganador = "V"
                self.actualizar_penales_ui()
                #self.guardar_estado()
                return

            # Empate en 5-5 ? agregar columna para muerte súbita si no existe
            if tirosL == tirosV == primeros:
                self._agregar_columna_penales_si_falta()
                self.actualizar_penales_ui()
                #self.guardar_estado()
                return

        # --- Muerte súbita ---
        # Si tiraron la misma cantidad y es mayor a 5
        
        
        if tirosL == tirosV and tirosL > primeros and golesL != golesV:
            self.ganador = "L" if golesL > golesV else "V"
            self.actualizar_penales_ui()
			#self.guardar_estado()
            return
            
            # Si están empatados y la pareja está completa ? agregar columna
        if tirosL == tirosV:
            self._agregar_columna_penales_si_falta()
        
        
        # No hay ganador todavía
        self.ganador = None
        self.actualizar_penales_ui()
    
    
    def _agregar_columna_penales_si_falta(self):
        # Si ya hay una columna sin usar en visitante/local, no agregar otra
        if "-" in self.penales_local and "-" in self.penales_visitante:
            return

        # Si no hay más espacio disponible ? agregar nueva columna - -
        self.penales_local.append("-")
        self.penales_visitante.append("-")

        # Crear labels visuales
        a = QLabel("-")
        b = QLabel("-")
        for lbl in (a, b):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            lbl.setFont(QFont("Arial", int(self.height() / 18) * 1.4))

        self.penales_local_labels.append(a)
        self.penales_visit_labels.append(b)

        self.row_local.addWidget(a)
        self.row_visit.addWidget(b)

        self.adjust_font_sizes()

    
    # ----------------------------
    # Lógica marcador
    # ----------------------------
    def add_gol(self, equipo, restar=False):
        if equipo == "local":
            self.goles_local = max(0, self.goles_local - 1) if restar else self.goles_local + 1
            self.lbl_local_score.setText(f"{self.goles_local}")
        else:
            self.goles_visitante = max(0, self.goles_visitante - 1) if restar else self.goles_visitante + 1
            self.lbl_visit_score.setText(f"{self.goles_visitante}")
        #self.guardar_estado()

    def iniciar_timer(self):
        # if finalizado, reset starting value per mode
        if self.lbl_estado.text() == "Finalizado":
            if self.descendente:
                self.tiempo = 1800
            else:
                self.tiempo = 0
            self.lbl_tiempo.setText(self._format_time(self.tiempo))

        if not self.contando:
            self.timer.start(1000)
            self.contando = True
            self.lbl_estado.setText("Contando...")
            #self.guardar_estado()

    def pausar_timer(self):
        if self.contando:
            self.timer.stop()
            self.contando = False
            self.lbl_estado.setText("Pausado")
            self.guardar_state_debounce_save()

    def toggle_modo(self):
        # not used directly ? handled via menu
        self.descendente = not self.descendente
        self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
        #self.guardar_estado()

    def cambiar_periodo(self):
        self.periodo = (self.periodo + 1) % len(self.periodos)
        self.lbl_periodo.setText(self.periodos[self.periodo])
        #self.guardar_estado()

    def actualizar_tiempo(self):
        # Esto NO corre si estamos en modo Penales y la vista de tiempo está oculta (pero timer puede estar parado)
        if self.penales_activo:
            # no actualizar tiempo visualmente en penales (tiempo no visible)
            return

        if self.descendente:
            if self.tiempo <= 0:
                self.tiempo = 0
                self.pausar_timer()
                self.lbl_estado.setText("Finalizado")
                try:
                    self.play_buzzer()
                except:
                    pass
                self.lbl_tiempo.setText("00:00")
                return
            self.tiempo -= 1
        else:
            if self.tiempo >= 1800:
                self.tiempo = 1800
                self.pausar_timer()
                self.lbl_estado.setText("Finalizado")
                try:
                    self.play_buzzer()
                except:
                    pass
                self.lbl_tiempo.setText("30:00")
                return
            self.tiempo += 1

        self.lbl_tiempo.setText(self._format_time(self.tiempo))

    def play_buzzer(self, wav_path="/home/ariel/Desktop/TableroMultideportes/buzzer.wav"):
        #Reproduce el wav por HDMI si es posible. Non-blocking.
        try:
            # intento rápido con aplay (no bloqueante)
            import subprocess, shlex
            subprocess.Popen(["aplay", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass

        try:
            # fallback PyQt QSound (puede necesitar instalar QtMultimedia)
            from PyQt5.QtMultimedia import QSound
            QSound.play(wav_path)
            return
        except Exception:
            pass

        # último recurso: os.system sin bloquear (puede dejar proceso)
        try:
            import os
            os.system(f"aplay {wav_path} >/dev/null 2>&1 &")
        except Exception:
            pass
    
    
    def _format_time(self, secs):
        m = secs // 60
        s = secs % 60
        return f"{m:02}:{s:02}"

    # ----------------------------
    # Resets
    # ----------------------------
    def reset_total(self):
        # full reset: goles, tiempo, periodo, penales cleared
        self.goles_local = 0
        self.goles_visitante = 0
        self.tiempo = 0 if not self.descendente else 1800
        self.periodo = 0
        self.penales_activo = False
        self.penales_local = ["-"] * 5
        self.penales_visitante = ["-"] * 5
        # Update UI
        self.actualizar_ui_completa()
        self.timer.stop()
        self.contando = False
        self.lbl_estado.setText("Pausado")
        #self.guardar_estado()

    # ----------------------------
    # UI helpers
    # ----------------------------
    def actualizar_ui_completa(self, startup=False):
        # scores
        self.lbl_local_score.setText(str(self.goles_local))
        self.lbl_visit_score.setText(str(self.goles_visitante))
        # period
        self.lbl_periodo.setText(self.periodos[self.periodo])
        # mode
        self.lbl_modo.setText("Modo: DESCENDENTE" if self.descendente else "Modo: ASCENDENTE")
        # tiempo label
        if self.penales_activo:
            self.lbl_tiempo.setVisible(False)
            self.lbl_estado.setVisible(False)
            self.lbl_periodo.setVisible(False)
            self.lbl_modo.setVisible(False)
            self.penales_frame.setVisible(True)
        else:
            self.lbl_tiempo.setVisible(True)
            self.lbl_estado.setVisible(True)
            self.lbl_periodo.setVisible(True)
            self.lbl_modo.setVisible(True)
            self.penales_frame.setVisible(False)
            # set displayed time
            self.lbl_tiempo.setText(self._format_time(self.tiempo))
            # state label
            self.lbl_estado.setText("Contando..." if self.contando else "Pausado")
        # penales labels
        for i in range(5):
            try:
                self.penales_local_labels[i].setText(self.penales_local[i])
                self.penales_visit_labels[i].setText(self.penales_visitante[i])
            except Exception:
                pass
        # menu labels updated
        self.render_menu()

    def guardar_state_debounce_save(self):
        if hasattr(self, "_debounce_timer"):
            self._debounce_timer.stop()

        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.guardar_estado)
        self._debounce_timer.start(100)  # 1 sec delay

    # ----------------------------
    # Resize handling (font scaling)
    # ----------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.adjust_font_sizes()
        return super().eventFilter(obj, event)

    def adjust_font_sizes(self):
        h = self.height()
        base = max(10, int(h / 18))

        # fuentes generales
        label_font = QFont("Arial", base)
        num_font = QFont("Arial", int(base * 1.8))
        
        penales_label_font = QFont("Arial", int(base * 1.4))   # L: V:
        penales_symbol_font = QFont("Arial", int(base * 1.4))  # símbolos O/X igual que L/V

        # labels generales
        for lbl in [self.lbl_local_txt, self.lbl_visit_txt, self.lbl_guion,
                    self.lbl_periodo, self.lbl_modo, self.penales_lbl_title]:
            lbl.setFont(label_font)
    
        # números de score
        for lbl in [self.lbl_local_score, self.lbl_visit_score]:
            lbl.setFont(num_font)

        # penales: símbolos y etiquetas L/V
        for lbl in self.penales_local_labels + self.penales_visit_labels:
            lbl.setFont(penales_symbol_font)

        # L: y V:
        if hasattr(self, "lbl_penales_L"):
            self.lbl_penales_L.setFont(penales_label_font)
        if hasattr(self, "lbl_penales_V"):
            self.lbl_penales_V.setFont(penales_label_font)
        
        # aplicar a cada label de penales (incluye los dinámicos)
        for lbl in self.penales_local_labels + self.penales_visit_labels:
            try:
                lbl.setFont(penales_symbol_font)
            except Exception:
                pass
        
        # menu labels
        for lbl in self.menu_labels:
            lbl.setFont(label_font)

        # tiempo / estado
        self.lbl_tiempo.setFont(label_font)
        self.lbl_estado.setFont(label_font)
        
        # asegurar altura fija relativa al alto actual de la ventana
        if hasattr(self, "menu_frame") and self.menu_frame is not None:
            h = self.height()
            #self.menu_frame.setFixedHeight(int(h * 0.18))  # 18% del alto de la ventana, funciona bien pero puede fallar en otros televisores de distinto tamaño
            # Ajuste dinámico del alto del menú basado en la fuente
            item_height = base * 2.4  # un poco más alto para que no corte las líneas
            menu_height = item_height * len(self.menu_items) + 28  # ligeramente mayor

            min_menu_height = int(h * 0.14)  # aumenta el mínimo permitido
            max_menu_height = int(h * 0.28)  # aumenta el margen máximo

            menu_height = max(min_menu_height, min(menu_height, max_menu_height))
            self.menu_frame.setFixedHeight(menu_height)


            # Clampear para que nunca quede muy chico ni demasiado grande
            menu_height = max(min_menu_height, min(menu_height, max_menu_height))
            self.menu_frame.setFixedHeight(menu_height)
        
        if getattr(self, "editando_tiempo", False):
            self.update_time_label_with_highlight()


    def editar_tiempo_handler(self, tecla):
        #Maneja ???? cuando se está editando tiempo inicial.
        # convertir tiempo_inicial en dígitos [M1 M2 S1 S2]
        secs = max(0, int(self.tiempo_inicial))
        m = secs // 60
        s = secs % 60
        dig = [m // 10, m % 10, s // 10, s % 10]

        if tecla == "S11":  # UP
            # límites: M1 max 5 (para no pasar 59min), M2 0-9, S1 0-5, S2 0-9
            if self.digito_tiempo == 0:
                dig[0] = min(5, dig[0] + 1)
            elif self.digito_tiempo == 1:
                dig[1] = min(9, dig[1] + 1)
            elif self.digito_tiempo == 2:
                dig[2] = min(5, dig[2] + 1)
            else:
                dig[3] = min(9, dig[3] + 1)

        elif tecla == "S15":  # DOWN
            if self.digito_tiempo in (0,1,2,3):
                dig[self.digito_tiempo] = max(0, dig[self.digito_tiempo] - 1)

        elif tecla == "S14":  # LEFT
            self.digito_tiempo = (self.digito_tiempo - 1) % 4

        elif tecla == "S16":  # RIGHT
            self.digito_tiempo = (self.digito_tiempo + 1) % 4

        # reconstruir tiempo_inicial y actualizar vista
        minutos = dig[0] * 10 + dig[1]
        segundos = dig[2] * 10 + dig[3]
        self.tiempo_inicial = minutos * 60 + segundos

        # Mostrar tiempo grande con el dígito en amarillo
        self.update_time_label_with_highlight()
        # y actualizar el menú para que muestre el nuevo valor también
        self.render_menu()

    def update_time_label_with_highlight(self):
        #Muestra self.tiempo_inicial en lbl_tiempo con el dígito seleccionado en amarillo.
        secs = int(self.tiempo_inicial)
        m = secs // 60
        s = secs % 60
        text = f"{m:02d}:{s:02d}"  # ejemplo "30:00"
        # mapping dígito -> índice en string "MM:SS" (0..4, con ':' en pos 2)
        mapping = {0:0, 1:1, 2:3, 3:4}
        idx = mapping.get(self.digito_tiempo, 0)
        # construir HTML con el dígito resaltado
        html = ""
        for i, ch in enumerate(text):
            if i == idx:
                html += f"<span style='color:yellow'>{ch}</span>"
            else:
                html += ch
        # usar fuente grande y centrado
        self.lbl_tiempo.setTextFormat(Qt.RichText)
        self.lbl_tiempo.setText(f"<div style='font-size:48px; text-align:center; color:white; font-family:Arial'>{html}</div>")

    def update_time_label_plain(self):
        #Muestra el tiempo actual (self.tiempo) sin resaltado en la etiqueta grande.
        secs = int(self.tiempo)
        m = secs // 60
        s = secs % 60
        self.lbl_tiempo.setTextFormat(Qt.PlainText)
        self.lbl_tiempo.setText(f"{m:02d}:{s:02d}")

    
    # ----------------------------
    # Close cleanup
    # ----------------------------
    def closeEvent(self, event):
        # save and cleanup
        try:
            self.guardar_estado()
        except:
            pass
        try:
            GPIO.cleanup()
        except:
            pass
        super().closeEvent(event)

# ----------------------------
# Ejecutable
# ----------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MarcadorHandball()
    win.showMaximized()
    sys.exit(app.exec_())

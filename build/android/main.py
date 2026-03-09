"""
REFInet Pillar — Android UI

Minimal Kivy interface for starting/stopping the Pillar daemon on Android.
The actual server runs in a background Android Service so it survives
the activity being paused or destroyed.
"""

import os
import sys

# On Android, set the data directory before importing pillar modules
if hasattr(sys, "getandroidapilevel"):
    from android.storage import app_storage_path  # noqa: F811
    os.environ["REFINET_HOME"] = os.path.join(app_storage_path(), ".refinet")

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

__version__ = "0.3.0"


class PillarApp(App):
    """Minimal Android controller for REFInet Pillar."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = None
        self.running = False

    def build(self):
        self.title = "REFInet Pillar"
        root = BoxLayout(orientation="vertical", padding=20, spacing=15)

        # Header
        header = Label(
            text="[b]REFInet Pillar[/b]\nSovereign Gopher Mesh Node",
            markup=True,
            font_size="20sp",
            size_hint_y=0.15,
            halign="center",
        )
        header.bind(size=header.setter("text_size"))
        root.add_widget(header)

        # Status
        self.status_label = Label(
            text="Status: [color=ff4444]Stopped[/color]",
            markup=True,
            font_size="16sp",
            size_hint_y=0.08,
        )
        root.add_widget(self.status_label)

        # Port info
        self.info_label = Label(
            text="Ports: 7070 (REFInet) · 7075 (WebSocket)",
            font_size="13sp",
            size_hint_y=0.06,
            color=(0.6, 0.6, 0.6, 1),
        )
        root.add_widget(self.info_label)

        # Log area
        scroll = ScrollView(size_hint_y=0.5)
        self.log_label = Label(
            text="Tap Start to launch your Pillar.\n",
            font_size="12sp",
            size_hint_y=None,
            halign="left",
            valign="top",
            text_size=(None, None),
        )
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        scroll.add_widget(self.log_label)
        root.add_widget(scroll)

        # Buttons
        btn_row = BoxLayout(size_hint_y=0.12, spacing=10)
        self.start_btn = Button(
            text="Start Pillar",
            font_size="16sp",
            background_color=(0.2, 0.7, 0.4, 1),
        )
        self.start_btn.bind(on_press=self.toggle_service)
        btn_row.add_widget(self.start_btn)

        self.status_btn = Button(
            text="Check Status",
            font_size="16sp",
            background_color=(0.3, 0.3, 0.5, 1),
        )
        self.status_btn.bind(on_press=self.check_status)
        btn_row.add_widget(self.status_btn)
        root.add_widget(btn_row)

        # Version footer
        footer = Label(
            text=f"v{__version__} · AGPLv3 · refinet.io",
            font_size="11sp",
            size_hint_y=0.05,
            color=(0.4, 0.4, 0.4, 1),
        )
        root.add_widget(footer)

        return root

    def log(self, msg):
        """Append a line to the log area."""
        self.log_label.text += msg + "\n"

    def toggle_service(self, *args):
        """Start or stop the Pillar background service."""
        if self.running:
            self.stop_service()
        else:
            self.start_service()

    def start_service(self):
        """Launch the Pillar as an Android background service."""
        try:
            if hasattr(sys, "getandroidapilevel"):
                from android import mActivity
                from jnius import autoclass

                service_class = autoclass(
                    "io.refinet.pillar.ServicePillarservice"
                )
                service_class.start(mActivity, "REFInet Pillar is running")
                self.service = service_class
                self.log("Starting Pillar service...")
            else:
                # Desktop fallback for testing
                self.log("Starting Pillar (desktop mode)...")
                import threading
                import asyncio

                # Add project root to path for imports
                project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from pillar import main as pillar_main

                def run_pillar():
                    asyncio.run(pillar_main("127.0.0.1", 7070, 70))

                self._thread = threading.Thread(target=run_pillar, daemon=True)
                self._thread.start()
                self.log("Pillar started on localhost:7070")

            self.running = True
            self.start_btn.text = "Stop Pillar"
            self.start_btn.background_color = (0.7, 0.2, 0.2, 1)
            self.status_label.text = "Status: [color=44ff44]Running[/color]"
            self.status_label.markup = True

        except Exception as e:
            self.log(f"ERROR: {e}")

    def stop_service(self):
        """Stop the background service."""
        try:
            if hasattr(sys, "getandroidapilevel") and self.service:
                from android import mActivity

                self.service.stop(mActivity)
                self.log("Stopping Pillar service...")
            else:
                self.log("Pillar stopped.")

            self.running = False
            self.start_btn.text = "Start Pillar"
            self.start_btn.background_color = (0.2, 0.7, 0.4, 1)
            self.status_label.text = "Status: [color=ff4444]Stopped[/color]"
            self.status_label.markup = True

        except Exception as e:
            self.log(f"ERROR stopping: {e}")

    def check_status(self, *args):
        """Show current Pillar status."""
        if self.running:
            self.log("Pillar is running on port 7070")
        else:
            self.log("Pillar is not running.")


if __name__ == "__main__":
    PillarApp().run()

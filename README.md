# Adlos Home Assistant Integration (HACS) 🎯

Die einfachste und eleganteste Möglichkeit, deine **Adlos App** direkt mit **Home Assistant** zu verbinden!

Mit dieser Integration fühlt sich Home Assistant in Adlos genau so nativ an wie Telegram oder Signal:

- 📱 **QR-Code Pairing in 3 Sekunden**: Einfach den in Home Assistant angezeigten QR-Code mit Adlos scannen – URL, Webhook & Token sind sofort eingerichtet.
- 📣 **Echte `notify.adlos` Aktion im Visuellen Editor**: Sende Benachrichtigungen, Fotos, Videos & automatische Kamera-Snapshots direkt aus deinen Automatisierungen.
- 💬 **Zwei-Wege-Kommunikation**: Antworte direkt im Adlos-Chat ("Schalte das Licht auf 50%"), und Home Assistant führt den Befehl über die Conversation Engine aus.

---

## 🚀 Installation

### Option 1: Über HACS (Empfohlen)
1. Öffne **HACS** in deiner Home Assistant Instanz.
2. Klicke oben rechts auf die 3 Punkte -> **Benutzerdefinierte Repositories**.
3. Füge die URL dieses Repositories hinzu: `https://github.com/gatzo23/ha-adlos` (Kategorie: **Integration**).
4. Suche nach **Adlos** und klicke auf **Herunterladen**.
5. Starte Home Assistant neu.

### Option 2: Manuelle Installation
Kopiere den Ordner `custom_components/adlos` direkt in deinen Home Assistant Ordner `/config/custom_components/adlos` und starte Home Assistant neu.

---

## ⚡ Einrichtung & QR-Code Pairing

1. Gehe in Home Assistant zu **Einstellungen -> Geräte & Dienste -> Integration hinzufügen**.
2. Suche nach **Adlos**.
3. Gib optional deine externe Home Assistant URL ein.
4. Home Assistant zeigt dir jetzt einen **QR-Code** an:
   - Öffne die **Adlos App** auf deinem Smartphone.
   - Scanne den QR-Code.
   - Der Chat **"Home Assistant"** öffnet sich sofort und ist startklar! 🎉

---

## 🛠️ Verwendung in Automatisierungen (`notify.adlos`)

Im visuellen Automatisierungs-Editor wählst du beim Erstellen einer Aktion einfach aus:
👉 **Aktion:** *Benachrichtigung senden über adlos (`notify.adlos`)*

### Beispiel 1: Text-Benachrichtigung
```yaml
action: notify.adlos
data:
  title: "Haushalt"
  message: "Die Waschmaschine ist fertig! 🧺"
```

### Beispiel 2: Automatische Kamera-Momentaufnahme
Sendet beim Auslösen der Bewegungserkennung sofort ein aktuelles Standbild der Kamera:
```yaml
action: notify.adlos
data:
  title: "Bewegung erkannt!"
  message: "Jemand steht an der Haustür."
  data:
    camera: camera.haustuer
```

### Beispiel 3: Foto oder Video aus lokalem Pfad / URL
```yaml
action: notify.adlos
data:
  title: "Kamerabild"
  message: "Snapshot aus der Garage"
  data:
    image: "/config/www/garage_snapshot.jpg"
```

---

## 💬 Zwei-Wege-Kommunikation (Chat -> Home Assistant)

Wenn du im Adlos-Chat an Home Assistant schreibst:
- **Du:** *"Schalte das Licht im Wohnzimmer auf 50%"*
- **Home Assistant:** *"Wohnzimmer Licht auf 50% gedimmt."*

Die Integration verarbeitet eingehende Nachrichten automatisch über die Home Assistant **Conversation Engine** oder löst das Ereignis `adlos_command_received` aus.

---

## 📄 Lizenz
MIT License

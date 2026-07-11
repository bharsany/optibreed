# Optibreed Windows Docker Telepítési Útmutató

Ez az útmutató lépésről lépésre bemutatja az Optibreed alkalmazás telepítését és futtatását Windows operációs rendszeren Docker segítségével. A Docker alkalmazása biztosítja, hogy a program egy elszigetelt, egységes környezetben fusson.

## Előfeltételek

A telepítés megkezdése előtt győződjön meg arról, hogy a Windows számítógépén telepítve vannak az alábbiak:

1. **Windows Subsystem for Linux (WSL 2)**
   - A WSL 2 jobb teljesítményt nyújt a Docker számára Windows alatt.
   - Nyisson meg egy PowerShell ablakot rendszergazdaként, és futtassa: `wsl --install`
   - Kérés esetén indítsa újra a számítógépet.

2. **Docker Desktop for Windows**
   - Töltse le a telepítőt a [hivatalos Docker weboldalról](https://docs.docker.com/desktop/install/windows-install/).
   - Futtassa a telepítőt, és győződjön meg róla, hogy a **"Use WSL 2 instead of Hyper-V"** opció ki van választva.
   - A telepítés után indítsa el a Docker Desktopot, és ellenőrizze, hogy a Docker motor fut-e (a tálcán lévő bálna ikon zöld színű, vagy a felületen az "Engine running" felirat látható).

3. **Git for Windows** (Opcionális, de ajánlott)
   - A forráskód egyszerű letöltéséhez telepítse a Git-et a [git-scm.com](https://gitforwindows.org/) oldalról.

---

## 1. Lépés: Az alkalmazás kódjának beszerzése

A kódnak a helyi Windows számítógépen kell lennie.

### "A" opció: Git használatával (Ajánlott)
Nyisson meg egy Parancssort (Command Prompt) vagy PowerShell-t és futtassa:
```cmd
git clone https://github.com/yourusername/optibreed.git
cd optibreed
```

### "B" opció: ZIP fájl letöltése
1. Töltse le a kódot ZIP formátumban a verziókezelő felületről (pl. GitHub, GitLab).
2. Csomagolja ki a ZIP fájlt egy tetszőleges mappába (pl. `C:\optibreed`).
3. Nyisson egy Parancssort vagy PowerShell-t, és lépjen a kicsomagolt mappába:
   ```cmd
   cd C:\optibreed
   ```

---

## 2. Lépés: A Docker image elkészítése (Build)

A mappában található [Dockerfile](file:///c:/Users/B%C3%A9la/Work/Parterv/Optibreed/optibreed/Dockerfile) tartalmazza a futtatási környezet felépítéséhez szükséges összes utasítást.

1. Nyissa meg a PowerShell-t vagy Parancssort.
2. Győződjön meg arról, hogy az alkalmazás gyökérmappájában van (ahol a [Dockerfile](file:///c:/Users/B%C3%A9la/Work/Parterv/Optibreed/optibreed/Dockerfile) is található).
3. Készítse el a Docker képfájlt az alábbi parancs futtatásával:

```cmd
docker build -t optibreed-app .
```

*Megjegyzés: A `-t optibreed-app` paraméter elnevezi az image-et. Ne felejtse el a pontot `.` a parancs végén—ez jelzi a Dockernek, hogy az aktuális mappát használja.*

A rendszer sebességétől és az internetkapcsolattól függően ez eltarthat néhány percig, amíg a Docker letölti az alap Python image-et, és telepíti a szükséges függőségeket (pl. libcairo2-dev, pandas, flask).

---

## 3. Lépés: A Docker konténer futtatása

Miután a képfájl elkészült, elindíthatja az alkalmazást egy Docker konténerben.

Futtassa az alábbi parancsot a konténer indításához:

```cmd
docker run -d -p 8080:8080 --name optibreed-container optibreed-app
```

**A parancs értelmezése:**
- `-d`: A konténer a háttérben fut (detached mode).
- `-p 8080:8080`: Összekapcsolja a Windows gép 8080-as portját a konténer belsejében lévő 8080-as porttal.
- `--name optibreed-container`: Egyértelmű nevet ad a futó konténernek.

*Megjegyzés: Ha más portra van szüksége, változtassa meg az első számot (pl. `-p 80:8080`, ha szabványos HTTP porton szeretné elérni).*

---

## 4. Lépés: A telepítés ellenőrzése

Az alkalmazás sikeres telepítésének és futásának ellenőrzéséhez:

1. **A konténer állapotának ellenőrzése**
   Futtassa az alábbi parancsot, hogy lássa, fut-e a konténer:
   ```cmd
   docker ps
   ```
   Látnia kell az `optibreed-container`-t az "Up" (fut) állapottal a listában.

2. **Hozzáférés az alkalmazáshoz**
   Nyissa meg a webböngészőjét, és lépjen az alábbi címre:
   [http://localhost:8080](http://localhost:8080)
   
   Ezután látnia kell a betöltődő Optibreed alkalmazást.

3. **Backend egészségi állapot (Health) ellenőrzése**
   Lépjen a [http://localhost:8080/health](http://localhost:8080/health) oldalra annak megerősítéséhez, hogy a háttérrendszer megfelelően válaszol.

---

## 5. Lépés: Az alkalmazás kezelése

Íme néhány hasznos parancs a Windows Docker környezet kezeléséhez:

- **Alkalmazás naplóinak (logs) megtekintése (hibaelhárításhoz):**
  ```cmd
  docker logs -f optibreed-container
  ```

- **Az alkalmazás leállítása:**
  ```cmd
  docker stop optibreed-container
  ```

- **Az alkalmazás újraindítása:**
  ```cmd
  docker start optibreed-container
  ```

- **A konténer teljes eltávolítása (ha újra szeretné buildelni vagy tisztán kezdeni):**
  ```cmd
  docker rm -f optibreed-container
  ```

---

## Gyakori Windows-specifikus problémák elhárítása

### 1. "Docker is not recognized as an internal or external command" (A Docker nem felismerhető belső vagy külső parancsként)
**Megoldás:** A Docker Desktop nem fut, vagy hiányzik a Windows PATH környezeti változójából. Indítsa el a Docker Desktopot a Start menüből, várja meg, amíg betölt, majd a PowerShell/Parancssor újraindítása után próbálja újra.

### 2. Foglalt port hiba (A 8080-as port már használatban van)
**Megoldás:** Egy másik alkalmazás már használja a 8080-as portot. Változtathat a konfiguráción oly módon, hogy egy másik portra irányítja az Optibreedet:
```cmd
docker run -d -p 8081:8080 --name optibreed-container optibreed-app
```
Ezután az alkalmazás a `http://localhost:8081` címen lesz elérhető.

### 3. Fájlútvonal- vagy formátum hibák (CRLF vs LF) a Build során
**Megoldás:** Ha a shell szkriptek sorvégi karaktereivel probléma adódik (a Windows alapértelmezett CRLF formátuma miatt), győződjön meg arról, hogy a Git megfelelően kezeli azokat, vagy töltse le újra a fájlokat linuxos sorvégződésekkel. Mivel mindent a Docker konténeren (Linuxon) belül futtatunk, a sikeres Docker build általában önmagában is megoldja ezt a problémát.

### 4. Magas memória-/CPU-használat
**Megoldás:** A Docker Desktop lehetővé teszi az erőforrások korlátozását.
Nyissa meg a Docker Desktop beállításait (Fogaskerék ikon) -> Resources -> Advanced (vagy a WSL integrációs beállításokat a verziótól függően). Itt megadhat specifikus RAM és Processzor (CPU) korlátokat, ha például az alkalmazás memóriahiánnyal küzd nagyon nagy adatbázisok/családfák (pedigrees) esetén.

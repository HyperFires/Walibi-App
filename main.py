import streamlit as st
import altair as alt
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import pandas as pd
from pytz import timezone
import folium
from streamlit_folium import st_folium
import re 


def get_wait_times():
    url = "https://www.looopings.nl/wachten/walibiholland"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    attractions = {}

    for row in soup.select("tr"):
        cols = row.find_all("td")
        if len(cols) >= 3:
            name = cols[0].text.strip()
            wait_td = cols[1]
            status_td = cols[2]  # <-- hier de fix

            status_text = status_td.text.strip()
            status_class = status_td.get("class", [])

            if "state_1" in status_class:
                # Attractie is open – probeer wachttijd te extraheren
                match = re.search(r"(\d+)", wait_td.text.strip())
                wait_time = int(match.group(1)) if match else 0
                attractions[name] = {"wait": wait_time, "status": "open"}
            elif "state_2" in status_class:
                attractions[name] = {"wait": None, "status": "closed"}
            elif "state_3" in status_class:
                attractions[name] = {"wait": None, "status": "breakdown"}
            elif "state_4" in status_class:
                attractions[name] = {"wait": None, "status": "maintenance"}
            else:
                attractions[name] = {"wait": None, "status": "unknown"}

    return attractions


def get_opening_hours():
    url = "https://www.looopings.nl/wachten/walibiholland"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    text_blocks = soup.find_all(text=True)
    for text in text_blocks:
        if "Open:" in text:
            cleaned = text.replace("Open:", "").replace("\xa0", " ").strip()
            return cleaned
    return None



def is_park_open(opening_hours_str):
    try:
        open_str, close_str = opening_hours_str.split(" - ")
        walibi_tz = pytz.timezone("Europe/Amsterdam")
        now = datetime.now(walibi_tz).time()

        open_time = datetime.strptime(open_str.strip(), "%H:%M").time()
        close_time = datetime.strptime(close_str.strip(), "%H:%M").time()

        if open_time < close_time:
            return open_time <= now <= close_time
        else:
            # Handle edge case where park might close after midnight
            return now >= open_time or now <= close_time
    except Exception as e:
        return None

def get_time_until_close(open_str, close_str):
    walibi_tz = pytz.timezone("Europe/Amsterdam")
    now = datetime.now(walibi_tz)

    open_time = datetime.strptime(open_str.strip(), "%H:%M").time()
    close_time = datetime.strptime(close_str.strip(), "%H:%M").time()

    open_dt_naive = datetime.combine(now.date(), open_time)
    close_dt_naive = datetime.combine(now.date(), close_time)

    open_dt = walibi_tz.localize(open_dt_naive)
    close_dt = walibi_tz.localize(close_dt_naive)

    if now > close_dt:
        return "🛑 The park is already closed."
    elif now < open_dt:
        delta = open_dt - now
        minutes = delta.seconds // 60
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0:
            return f"🕐 Opens in {hours}h {mins}m"
        else:
            return f"🕐 Opens in {mins} minutes"
    else:
        delta = close_dt - now
        minutes = delta.seconds // 60
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0:
            return f"⌛ Closes in {hours}h {mins}m"
        else:
            return f"⌛ Closes in {mins} minutes"

def fetch_historical_wait_times(park_id=53):
    url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
    resp = requests.get(url, headers={"User-Agent": "WalibiOptimizer/1.0"})
    data = resp.json()

    records = []
    now = datetime.utcnow()
    for land in data.get("lands", []):
        for ride in land.get("rides", []):
            records.append({
                "timestamp": now,
                "ride": ride.get("name"),
                "wait_time": ride.get("wait_time"),
                "is_open": ride.get("is_open")
            })
    return pd.DataFrame(records)

def wait_time_color(wait, status=None):
    if status == "maintenance":
        return "gray"
    elif status == "breakdown":
        return "#2a0000"
    elif wait is None:
        return "#FF1493"
    elif wait <= 10:
        return "green"          
    elif wait < 20:
        return "#7bb172"        
    elif wait <= 30:
        return "orange"
    else:
        return "red"

def get_full_wikipedia_text(title: str, max_paragraphs: int = 15) -> str:
    url = f"https://nl.wikipedia.org/wiki/{title}"
    response = requests.get(url)

    if response.status_code != 200:
        return "⚠️ Wikipedia-pagina kon niet worden opgehaald."

    soup = BeautifulSoup(response.text, "html.parser")
    content = soup.find("div", {"id": "mw-content-text"})

    if not content:
        return "⚠️ Geen geschikte tekst gevonden op de pagina."

    # Haal alle paragrafen op binnen de hoofdinhoud
    paragraphs = content.find_all("p")
    clean_paragraphs = []

    for p in paragraphs:
        text = p.get_text().strip()

        # Verwijder referenties zoals [1], [2], etc.
        text = re.sub(r'\[\d+\]', '', text)

        # Herstel spaties tussen woorden die aan elkaar geplakt waren
        text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

        # Voeg alleen zinnige paragrafen toe
        if len(text) > 50:
            clean_paragraphs.append(text)

        if len(clean_paragraphs) >= max_paragraphs:
            break

    if not clean_paragraphs:
        return "⚠️ Geen geschikte tekst gevonden op de pagina."

    return "\n\n".join(clean_paragraphs)

# ---- Score formula ----
def score(wait_time, walk_time, user_score):
    return wait_time + walk_time - user_score * 3

# ---- Distance matrix ----
distance_matrix = {
    "UNTAMED": {"Lost Gravity": 6, "Xpress: Platform 13": 7, "YOY THRILL side": 10, "Space Shot": 2, "El Rio Grande": 8, "YOY CHILL side": 10, "Speed Of Sound": 10, "Goliath": 4, "Condor": 5, "Crazy River": 5},
    "Lost Gravity": {"UNTAMED": 6, "Xpress: Platform 13": 6, "YOY THRILL side": 9, "Space Shot": 7, "El Rio Grande": 7, "YOY CHILL side": 9, "Speed Of Sound": 4, "Goliath": 9, "Condor": 7, "Crazy River": 2},
    "Xpress: Platform 13": {"UNTAMED": 7, "Lost Gravity": 6, "YOY THRILL side": 3, "Space Shot": 6, "El Rio Grande": 3, "YOY CHILL side": 3, "Speed Of Sound": 2, "Goliath": 8, "Condor": 6, "Crazy River": 6},
    "YOY THRILL side": {"UNTAMED": 10, "Lost Gravity": 9, "Xpress: Platform 13": 3, "Space Shot": 7, "El Rio Grande": 4, "YOY CHILL side": 0, "Speed Of Sound": 8, "Goliath": 11, "Condor": 6, "Crazy River": 9},
    "Space Shot": {"UNTAMED": 2, "Lost Gravity": 7, "Xpress: Platform 13": 6, "YOY THRILL side": 7, "El Rio Grande": 5, "YOY CHILL side": 7, "Speed Of Sound": 11, "Goliath": 3, "Condor": 3, "Crazy River": 6},
    "El Rio Grande": {"UNTAMED": 8, "Lost Gravity": 7, "Xpress: Platform 13": 3, "YOY THRILL side": 4, "Space Shot": 5, "YOY CHILL side": 4, "Speed Of Sound": 8, "Goliath": 9, "Condor": 5, "Crazy River": 7},
    "YOY CHILL side": {"UNTAMED": 10, "Lost Gravity": 9, "Xpress: Platform 13": 3, "YOY THRILL side": 0, "Space Shot": 7, "El Rio Grande": 4, "Speed Of Sound": 8, "Goliath": 11, "Condor": 6, "Crazy River": 9},
    "Speed Of Sound": {"UNTAMED": 10, "Lost Gravity": 4, "Xpress: Platform 13": 2, "YOY THRILL side": 8, "Space Shot": 11, "El Rio Grande": 8, "YOY CHILL side": 8, "Goliath": 11, "Condor": 5, "Crazy River": 8},
    "Goliath": {"UNTAMED": 4, "Lost Gravity": 9, "Xpress: Platform 13": 8, "YOY THRILL side": 11, "Space Shot": 3, "El Rio Grande": 9, "YOY CHILL side": 11, "Speed Of Sound": 11, "Condor": 5, "Crazy River": 9},
    "Condor": {"UNTAMED": 5, "Lost Gravity": 7, "Xpress: Platform 13": 6, "YOY THRILL side": 6, "Space Shot": 3, "El Rio Grande": 5, "YOY CHILL side": 6, "Speed Of Sound": 9, "Goliath": 5, "Crazy River": 8},
    "Crazy River": {"UNTAMED": 5, "Lost Gravity": 2, "Xpress: Platform 13": 6, "YOY THRILL side": 9, "Space Shot": 6, "El Rio Grande": 7, "YOY CHILL side": 9, "Speed Of Sound": 8, "Goliath": 9, "Condor": 8},
}

ride_locations = {
    "UNTAMED": (52.4426, 5.76115),
    "Lost Gravity": (52.4425, 5.76622),
    "Xpress: Platform 13": (52.439, 5.76409),
    "YOY THRILL side": (52.439473, 5.763067),  # origineel
    "Space Shot": (52.4417, 5.76104),
    "El Rio Grande": (52.4399, 5.76366),
    "YOY CHILL side": (52.439473 + 0.00015, 5.763067 + 0.000015),  # iets verschoven
    "Speed Of Sound": (52.4406, 5.76816),
    "Goliath": (52.4386, 5.76156),
    "Condor": (52.4405, 5.76151),
    "Crazy River": (52.4422, 5.76459),
}


TARGET_RIDES = list(distance_matrix.keys())

# ---- Streamlit UI ----
st.set_page_config(page_title="Walibi Ride Optimizer", layout="centered")
st.title("🎢 Walibi Ride Optimizer")

tab1, tab2, tab3 = st.tabs([
    "🚀 Ride Optimizer",  
    "🗺️ Overview Attractions",
    "📖 Park Info"
])


with tab1:
    opening_hours = get_opening_hours()
    if opening_hours:
        open_status = is_park_open(opening_hours)
        st.markdown("### 🕒 Park Opening Hours")
        st.write(f"Today: {opening_hours}")

        # Toon open/gesloten status
        if open_status is True:
            st.success("✅ The park is currently **OPEN**")
        elif open_status is False:
            st.error("❌ The park is currently **CLOSED**")
        else:
            st.warning("⚠️ Could not determine current open status.")

        # Toon countdown tot opening of sluiting
        try:
            open_str, close_str = opening_hours.split(" - ")
            time_until = get_time_until_close(open_str, close_str)
            st.info(time_until)
        except Exception:
            st.warning("⚠️ Could not calculate time until open/close.")
    else:
        st.warning("⚠️ Opening hours not found on the site.")



    st.write("Find the best ride to go to next based on real-time wait times, your location, and preferences.")

    wait_data = get_wait_times()
    open_rides = [r for r in TARGET_RIDES if wait_data.get(r, {}).get("status") == "open"]

    walibi_tz = timezone("Europe/Amsterdam")
    local_time = datetime.now(walibi_tz)
    st.caption(f"🕒 Gegevens bijgewerkt op {local_time.strftime('%H:%M:%S')}")


    if not open_rides:
        st.warning("No thrill rides are currently open.")
    

    current_ride = st.selectbox("🎡 Which ride did you just exit?", open_rides)

    max_wait = st.slider("⏳ Max wait time (min)", 0, 120, 45)
    max_walk = st.slider("🚶 Max walking time (min)", 0, 20, 10)

    st.markdown("### 🎯 Rate each ride (0 = skip, 10 = must-do)")

    if "last_preset" not in st.session_state:
        st.session_state["last_preset"] = "🎚️ Custom"

    preset = st.selectbox(
        "🎛️ Choose a preference preset",
        [
            "🎚️ Custom",
            "✅ All On",
            "🎢 Roller Coasters Only",
            "🚫 No Water",
            "⚡ Short Wait Boost",
            "🎢 Thrill Seeker",
            "🧘 Chill Mode",
        ],
        index=[
            "🎚️ Custom",
            "✅ All On",
            "🎢 Roller Coasters Only",
            "🚫 No Water",
            "⚡ Short Wait Boost",
            "🎢 Thrill Seeker",
            "🧘 Chill Mode",
        ].index(st.session_state["last_preset"]),
    )


    # Define ride categories
    water_rides = ["Crazy River", "El Rio Grande"]
    thrill_rides = [
        "UNTAMED", "Lost Gravity", "Goliath",
        "Speed Of Sound", "Condor",
        "YOY THRILL side", "Xpress: Platform 13", "Space Shot"
    ]
    chill_rides = ["YOY CHILL side", "Crazy River", "El Rio Grande"]
    roller_coasters = [
        "UNTAMED", "Lost Gravity", "Goliath",
        "Speed Of Sound", "Condor", "Xpress: Platform 13",
        "YOY THRILL side", "YOY CHILL side"
    ]

    # Apply presets to session_state
    if preset != st.session_state["last_preset"]:
        for ride in open_rides:
            wait = wait_data[ride]["wait"] or 0
            if preset == "✅ All On":
                st.session_state[ride] = 5
            elif preset == "🎢 Roller Coasters Only":
                st.session_state[ride] = 5 if ride in roller_coasters else 0
            elif preset == "🚫 No Water":
                st.session_state[ride] = 0 if ride in water_rides else 5
            elif preset == "⚡ Short Wait Boost":
                st.session_state[ride] = 8 if wait <= 5 else 5
            elif preset == "🎢 Thrill Seeker":
                st.session_state[ride] = 10 if ride in thrill_rides else 5
            elif preset == "🧘 Chill Mode":
                st.session_state[ride] = 8 if ride in chill_rides else 0
        st.session_state["last_preset"] = preset


    # Reset button
    if st.button("🔄 Reset Ratings"):
        for ride in open_rides:
            st.session_state[ride] = 5
        st.session_state["last_preset"] = "🎚️ Custom"


    ride_scores = {}
    for ride in open_rides:
        wait = wait_data[ride]["wait"]
        wait_display = f"⏱️ {wait} min" if wait is not None else "⏱️ onbekend"

        # Titel boven de slider
        st.markdown(f"**{ride} – {wait_display}**")

        # Slider eronder
        if ride not in st.session_state:
            st.session_state[ride] = 5

        previous_value = st.session_state[ride]
        current_value = st.slider("", 0, 10, key=ride, label_visibility="collapsed")
        ride_scores[ride] = current_value

        if current_value != previous_value and st.session_state["last_preset"] != "🎚️ Custom":
            st.session_state["last_preset"] = "🎚️ Custom"

        # Eventueel een scheidingslijn tussen attracties
        st.markdown("<br>", unsafe_allow_html=True)


    st.markdown("---")


    # ---- Optimization logic ----
    # Filter out rides that user scored 0
    filtered_rides = {ride: score for ride, score in ride_scores.items() if score > 0}
    best_ride = None
    best_score = float("inf")


    for ride, preference in filtered_rides.items():
        wait_time = wait_data[ride]["wait"]

        if ride == current_ride:
            walk_time = 0
        else:
            walk_time = distance_matrix.get(current_ride, {}).get(ride, 10)

        if wait_time is not None and (wait_time > max_wait or walk_time > max_walk):
            continue

        s = score(wait_time, walk_time, preference)
        if s < best_score:
            best_score = s
            best_ride = ride



    if best_ride:
        st.success(f"🎢 Best next ride: **{best_ride}**")
        st.write(f"⏳ Wait time: {wait_data[best_ride]['wait']} minutes")
        walk_time = distance_matrix.get(current_ride.strip(), {}).get(best_ride.strip())
        if current_ride == best_ride:
            walk_time = 0
        else:
            walk_time = distance_matrix.get(current_ride.strip(), {}).get(best_ride.strip())

        if walk_time is not None:
            st.write(f"🚶 Walking time: {walk_time} minutes")
        else:
            st.warning("Walking time data not available for selected rides.")


    else:
        st.warning("No rides fit your limits.")

    # ---- Show closed rides for transparency ----
    closed_rides = [
    ride for ride in TARGET_RIDES
    if wait_data.get(ride, {}).get("status") in ["closed", "maintenance", "breakdown"]
]


    status_display = {
    "closed": ("🔴", "Closed"),
    "maintenance": ("🔧", "Maintenance"),
    "breakdown": ("⚠️", "Storing"),
}

    for ride in closed_rides:
        status = wait_data.get(ride, {}).get("status", "unknown")
        emoji, label = status_display.get(status, ("❔", status))
        st.markdown(
            f"- **{ride}** {emoji} &nbsp;&nbsp;<span style='color:red;'>[{label.upper()}]</span>",
            unsafe_allow_html=True
        )

    
    # Filter alleen rides met coördinaten
    valid_rides = {r: loc for r, loc in ride_locations.items() if loc != "TBD"}

    # 🗺️ Streamlit kaartweergave
    st.markdown("### 🗺️ Interactive map of the park")
    m = folium.Map(location=[52.441, 5.763], zoom_start=17)

    for ride, (lat, lon) in valid_rides.items():
        ride_info = wait_data.get(ride, {})
        wait = ride_info.get("wait")
        status = ride_info.get("status", "unknown")

        # Looptijd van huidige locatie naar deze attractie (indien bekend)
        walk_time = None
        if current_ride in distance_matrix and ride in distance_matrix[current_ride]:
            walk_time = distance_matrix[current_ride][ride]

        popup_lines = [f"<b>{ride}</b>"]
        if wait is not None:
            popup_lines.append(f"Wachttijd: {wait} min")
        else:
            popup_lines.append(f"Status: {status}")

        if walk_time is not None:
            popup_lines.append(f"Looptijd: {walk_time} min")

        popup = "<br>".join(popup_lines)

        if wait is not None:
        wait_text = f"{wait}m"
    else:
        if status == "closed":
            wait_text = "❌"
        elif status == "maintenance":
            wait_text = "🔧"
        elif status == "breakdown":
            wait_text = "⚠️"
        else:
            wait_text = "?"

        # Het rode uitroepteken is hier verwijderd

        folium.Marker(
            location=(lat, lon),
            popup=popup,
            icon=folium.DivIcon(html=f"""
                <div style="
                    background-color: {wait_time_color(wait, status)};
                    color: white;
                    padding: 6px 10px;
                    min-width: 32px;
                    border-radius: 6px;
                    font-size: 16px;
                    font-weight: bold;
                    text-align: center;
                    display: inline-block;
                    box-shadow: 1px 1px 3px rgba(0,0,0,0.3);
                ">
                    {wait_text}
                </div>
            """)
        ).add_to(m)



    # Markeer huidige locatie (laatste attractie)
    if current_ride in valid_rides:
        folium.Marker(
            location=valid_rides[current_ride],
            popup="📍 Jij bent hier (net geweest)",
            icon=folium.Icon(color="blue", icon="star")
        ).add_to(m)

    # Toon de kaart
    st_data = st_folium(m, width=700, height=500)

with tab2:
    st.header("📋 Attraction Overview")

    # Sort option dropdown
    sort_option = st.selectbox(
        "📊 Sort Attractions based on:",
        ["Alphabetical", "Wait time (low to high)", "Wait time (high to low)", "Status"]
    )

    ride_table = []

    for ride in TARGET_RIDES:
        ride_info = wait_data.get(ride, {})
        status = ride_info.get("status")
        wait = ride_info.get("wait")

        if status == "open":
            display = f"🟢 {wait} min" if wait is not None else "🟢 Unknown"
        elif status == "closed":
            display = "🔴 Closed"
        elif status == "maintenance":
            display = "🔧 Maintenance"
        elif status == "breakdown":
            display = "⚠️ Storing"
        else:
            display = "❔ Unknown"

        ride_table.append({
            "Attraction": ride,
            "Status / Wait Time": display
        })

    df_overview = pd.DataFrame(ride_table)

    # Sorting logic
    if sort_option == "Alphabetical":
        df_overview = df_overview.sort_values("Attraction")

    elif sort_option == "Wait time (low to high)":
        df_overview["WaitTimeNum"] = df_overview["Status / Wait Time"].str.extract(r'(\d+)').astype(float)
        df_overview = df_overview.sort_values("WaitTimeNum", na_position="last")

    elif sort_option == "Wait time (high to low)":
        df_overview["WaitTimeNum"] = df_overview["Status / Wait Time"].str.extract(r'(\d+)').astype(float)
        df_overview = df_overview.sort_values("WaitTimeNum", ascending=False, na_position="last")

    elif sort_option == "Status":
        # Define sorting priority for status icons
        status_order = {"🟢": 0, "⚠️": 1, "🔴": 2}
        df_overview["StatusCode"] = df_overview["Status / Wait Time"].str[0].map(status_order)
        df_overview = df_overview.sort_values("StatusCode")

    # Drop helper columns if they exist
    df_overview = df_overview.drop(columns=["WaitTimeNum", "StatusCode"], errors="ignore")

    # Display table
    st.dataframe(df_overview, use_container_width=True, hide_index=True)

with tab3:
    st.header("📖 Informatie over het park en attracties")

    # Algemene parkintroductie in een expander
    with st.expander("🎢 Over Walibi Holland (klik om te openen)"):
        with st.spinner("Wikipedia-info over Walibi Holland laden..."):
            park_intro = get_full_wikipedia_text("Walibi_Holland")
            st.write(park_intro)
            st.markdown("[🔗 Bekijk Walibi Holland op Wikipedia](https://nl.wikipedia.org/wiki/Walibi_Holland)")

    st.markdown("---")

    # Mapping van attractienamen naar Wikipedia-paginatitels
    ride_wiki_titles = {
        "UNTAMED": "Untamed_(Walibi_Holland)",
        "Lost Gravity": "Lost_Gravity",
        "Xpress: Platform 13": "Xpress:_Platform_13",
        "YOY THRILL side": "YOY",
        "YOY CHILL side": "YOY",
        "Space Shot": "Space_Shot_(Walibi_Holland)",
        "El Rio Grande": "El_Rio_Grande",
        "Speed Of Sound": "Speed_of_Sound_(achtbaan)",
        "Goliath": "Goliath_(Walibi_Holland)",
        "Condor": "Condor_(Walibi_Holland)",
        "Crazy River": "Crazy_River"
    }

    st.subheader("🎡 Kies een attractie voor meer info")
    keuze = st.selectbox("Attractie", list(ride_wiki_titles.keys()))

    wiki_title = ride_wiki_titles.get(keuze)

    if wiki_title:
        with st.spinner(f"Informatie ophalen over {keuze}..."):
            intro_text = get_full_wikipedia_text(wiki_title)
            st.markdown(f"### {keuze}")
            st.write(intro_text)
            st.markdown(f"[🔗 Bekijk volledige Wikipedia-pagina](https://nl.wikipedia.org/wiki/{wiki_title})")
    else:
        st.info("Geen Wikipedia-informatie beschikbaar voor deze attractie.")

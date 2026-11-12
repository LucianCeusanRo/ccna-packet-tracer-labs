# Laboratoare Packet Tracer — notițe de înțeles, nu de tocit

Aceste patru laboratoare sunt exerciții de Cisco IOS pentru Packet Tracer, nu rețele de producție. Configurațiile sunt în folderele `01-vlan-trunk` … `04-acl`.

Ideea e să poți explica fiecare comandă la un interviu, nu doar să o lipești. Mai jos e de ce funcționează, pe scurt, în română.

Dispozitivele din README (2960, 2911) sunt cele obișnuite în Packet Tracer. Dacă folosești un 3560, ține minte excepția de la laboratorul 1.

---

## 1. VLAN + trunk

**Ce demonstrezi.** Două switch-uri pot extinde aceleași VLAN-uri printr-un singur cablu, dacă acel link e trunk 802.1Q. Calculatoarele din același VLAN se văd. Cele din VLAN-uri diferite, nu — lipsește un rutier, deci cadrul nu are unde să fie rutate.

**De ce merge.** Un port *access* trimite cadre fără tag, pentru un singur VLAN. Un port *trunk* pune un tag 802.1Q pe cadre, ca vecinul să știe în ce VLAN sunt. `switchport trunk allowed vlan 10,20` limitează trunk-ul la VLAN-urile din laborator (e mai curat decât să lași toate VLAN-urile). `switchport nonegotiate` oprește DTP, ca modul (access sau trunk) să rămână cel pe care l-ai setat tu, nu unul negociat. `spanning-tree portfast` pe porturile către PC evită așteptarea STP; nu-l pune pe trunk, între switch-uri.

**Excepție de platformă.** Pe 2960, `switchport trunk encapsulation dot1q` nu există și e respinsă. Pe 3560 trebuie pusă *înainte* de `switchport mode trunk`.

**Verificare.** `show vlan brief` (VLAN 10 și 20 active, porturile access în VLAN-ul corect), `show interfaces trunk` (Gi0/1 trunk, allowed 10,20). Ping PC1 → PC3 reușește; PC1 → PC2 eșuează.

**Greșeală frecventă.** Un capăt access și celălalt trunk; VLAN creat doar pe un switch; ping între VLAN-uri așteptat să meargă fără rutare.

---

## 2. Rutare inter-VLAN (router-on-a-stick)

**Ce demonstrezi.** Un singur port fizic de rutier, cu subinterfețe, poate fi gateway pentru mai multe VLAN-uri.

**De ce merge.** Switch-ul trimite pe trunk cadre tag-uite. Rutierul desface tag-ul pe subinterfața care are `encapsulation dot1Q 10` sau `20` și tratează fiecare subinterfață ca o rețea conectată. De aceea interfața fizică `GigabitEthernet0/0` n-are adresă IP: adresele (192.168.10.1 și 192.168.20.1) stau pe `.10` și `.20`. PC-urile trebuie să aibă aceste adrese ca default gateway, altfel pachetul inter-VLAN nu pleacă spre rutier.

`show ip route` trebuie să arate două rute *Connected* (C). Nu ai nevoie de OSPF sau rute statice în acest laborator: rutarea e între rețele direct conectate pe același rutier.

**Verificare.** `show ip interface brief` (subinterfețele up), `show vlans` pe rutier, ping de la PC1 la 192.168.20.10.

**Greșeală frecventă.** IP pus pe interfața fizică, nu pe subinterfață; `encapsulation` lipsă sau VLAN ID greșit; trunk-ul de pe switch nu permite VLAN-ul; gateway uitat pe PC.

---

## 3. OSPF, o singură zonă (area 0)

**Ce demonstrezi.** Trei rutiere din area 0 devin vecini, își anunță loopback-urile și pot da ping între ele pe 1.1.1.1, 2.2.2.2, 3.3.3.3.

**De ce merge.** `router ospf 1` pornește procesul. `router-id` e setat explicit pe adresa de loopback, ca ID-ul să fie stabil și ușor de recunoscut în `show ip ospf neighbor`. Comanda `network 10.0.12.0 0.0.0.3 area 0` nu e o rută: e un *filtru* care spune „orice interfață a cărei adresă cade în 10.0.12.0/30 participă la OSPF în area 0”. Wildcard-ul pentru /30 este `0.0.0.3` (inversul măștii 255.255.255.252). Pentru loopback /32, wildcard-ul este `0.0.0.0`.

Process ID-ul (1) e local; nu trebuie să coincidă cu vecinul ca să se formeze adiacența, dar în laborator e același, ca să fie lizibil. Area 0 este zona backbone; aici e singura zonă, deci rutele apar ca intra-area (`O`), nu `O IA`.

**Verificare.** Pe fiecare rutier, `show ip ospf neighbor` — doi vecini în starea **FULL**. `show ip route ospf` — loopback-urile celorlalți. `ping 2.2.2.2` de pe R1.

**Greșeală frecventă.** Wildcard greșit (de exemplu 0.0.0.255 pe un /30); interfață down; area diferită pe un capăt; `router-id` duplicat pe două rutiere; te aștepți la vecini înainte ca link-ul să fie up.

---

## 4. ACL standard și extins

**Ce demonstrezi.** Un ACL *standard* filtrează doar după sursă, deci îl pui cât mai aproape de destinație. Un ACL *extins* poate filtra sursă, destinație și protocol, deci îl pui cât mai aproape de sursă. În laborator: varianta A blochează tot Guest-ul spre Staff; varianta B lasă doar HTTP către serverul 192.168.10.10.

**De ce merge — standard (ACL 10, out pe G0/0.10).** `deny 192.168.20.0 0.0.0.255` potrivește orice pachet a cărui *sursă* e în Guest. E aplicat *outbound* pe subinterfața Staff, adică pe pachetele care *ies* spre VLAN 10. `permit any` de la final e obligatoriu: fără el, *implicit deny* ar arunca și traficul legitim care iese pe G0/0.10 (inclusiv răspunsuri din Staff).

**De ce merge — extins (GUEST_TO_STAFF, in pe G0/0.20).** Prima linie lasă TCP port 80 de la Guest către exact host-ul 192.168.10.10. A doua interzice orice alt IP de la Guest către rețeaua Staff. A treia (`permit ip any any`) lasă restul (de exemplu Guest spre alte destinații). E aplicat *inbound* pe G0/0.20, deci pachetele sunt judecate când *intră* în rutier din VLAN Guest, înainte să fie rulate.

Nu aplica ambele variante în același timp. Dacă ai testat standardul, șterge-l înainte de extins (comenzile sunt în `R1-extended-acl.cfg`).

Wildcard-ul din ACL este același tip ca la OSPF: `0.0.0.255` înseamnă /24. Nu pune masca 255.255.255.0 într-un ACL — IOS o citește altfel.

**Verificare.** `show access-lists` — contoarele (hits) trebuie să crească după un ping sau un HTTP. Cu standardul, ping-ul Guest → Staff eșuează. Cu extinsul, HTTP către .10 trece, ping-ul către Staff eșuează.

**Greșeală frecventă.** ACL standard pus la sursă (blochezi prea mult, sau nimic din ce credeai); `permit any` uitat; direcție `in`/`out` inversată; ambele ACL-uri rămase active; confuzie între mască și wildcard.

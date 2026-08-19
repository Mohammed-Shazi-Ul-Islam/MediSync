"""
app/services/medical_kb.py

Curated medical knowledge base for the MediSync RAG pipeline.

Each entry is a dict with:
  - "text"       : the document that gets embedded and stored in ChromaDB
  - "metadata"   : structured fields stored alongside the embedding for filtering

The text is written as a dense clinical summary so that semantic search retrieves
the right conditions when a patient's symptom text is used as the query.

Coverage:
  - Cardiology    : MI, angina, PE, aortic dissection, arrhythmia, heart failure
  - Neurology     : stroke, TIA, migraine, seizure, meningitis, subarachnoid
  - Respiratory   : asthma, COPD, pneumonia, pneumothorax
  - Abdominal     : appendicitis, bowel obstruction, pancreatitis, cholecystitis, AAA
  - Systemic      : sepsis, anaphylaxis, DKA, hypoglycaemia
  - MSK / Trauma  : fracture, sprain, DVT
  - ENT / Derm    : anaphylaxis, cellulitis, epiglottitis
  - Urology       : UTI, renal colic
  - Psych         : panic attack (mimics cardiac emergency)
  - General       : fever, dehydration, viral illness
"""

from __future__ import annotations

MEDICAL_KB: list[dict] = [
    # ─── Cardiology ────────────────────────────────────────────────────────────
    {
        "text": (
            "ST-Elevation Myocardial Infarction (STEMI / Heart Attack): "
            "Crushing, pressure-like chest pain radiating to the left arm, jaw, or back. "
            "Associated with diaphoresis (sweating), nausea, vomiting, dyspnea, and syncope. "
            "Sudden onset. Classic red flags: left arm pain, jaw pain, cold sweat, feeling of doom. "
            "Requires immediate emergency intervention — call 911. Every minute counts (door-to-balloon < 90 min). "
            "Risk factors: hypertension, diabetes, smoking, hypercholesterolaemia, family history of CAD."
        ),
        "metadata": {
            "condition": "STEMI / Myocardial Infarction",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I21",
            "keywords": "chest pain, heart attack, MI, STEMI, left arm, jaw pain, diaphoresis, sweating",
        },
    },
    {
        "text": (
            "Unstable Angina / NSTEMI: Chest tightness or pressure at rest or with minimal exertion. "
            "May radiate to arm, jaw, or back. Unlike stable angina, does not fully resolve with nitroglycerine. "
            "Associated symptoms: shortness of breath, sweating, nausea. "
            "High-risk condition requiring urgent cardiac evaluation and hospital admission. "
            "Key differentiator from STEMI: no persistent ST elevation on ECG."
        ),
        "metadata": {
            "condition": "Unstable Angina / NSTEMI",
            "urgency": "critical",
            "specialist": "cardiologist",
            "icd10": "I20.0",
            "keywords": "chest tightness, angina, rest pain, arm pain, cardiac",
        },
    },
    {
        "text": (
            "Pulmonary Embolism (PE): Sudden onset of pleuritic chest pain (sharp, worsens with breathing), "
            "dyspnea, tachycardia, haemoptysis (coughing blood). "
            "Risk factors: recent surgery, prolonged immobility, DVT, oral contraceptives, malignancy. "
            "Can present with leg swelling or pain from underlying DVT. "
            "Life-threatening — requires immediate CT pulmonary angiography and anticoagulation."
        ),
        "metadata": {
            "condition": "Pulmonary Embolism",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I26",
            "keywords": "pleuritic chest pain, shortness of breath, blood, coughing, DVT, PE, embolism",
        },
    },
    {
        "text": (
            "Aortic Dissection: Sudden, severe tearing or ripping chest pain that radiates to the back. "
            "Often described as the worst pain of one's life. May present with unequal blood pressure in arms, "
            "pulse deficits, neurological symptoms, or syncope. "
            "Hypertension is the primary risk factor. Marfan syndrome increases risk. "
            "Surgical emergency — Type A involves the ascending aorta and requires immediate surgery."
        ),
        "metadata": {
            "condition": "Aortic Dissection",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I71.0",
            "keywords": "tearing chest pain, back pain, ripping, worst pain, aorta",
        },
    },
    {
        "text": (
            "Cardiac Arrhythmia / Atrial Fibrillation: Irregular heartbeat, palpitations, racing heart, "
            "or fluttering sensation in the chest. May cause dizziness, lightheadedness, syncope, or dyspnea. "
            "AF increases stroke risk. Requires ECG. Unstable arrhythmias causing haemodynamic compromise need "
            "urgent cardioversion. Stable AF can often be managed with rate/rhythm control medications."
        ),
        "metadata": {
            "condition": "Cardiac Arrhythmia / AFib",
            "urgency": "moderate",
            "specialist": "cardiologist",
            "icd10": "I48",
            "keywords": "palpitations, irregular heartbeat, racing heart, dizziness, AFib",
        },
    },
    {
        "text": (
            "Acute Heart Failure / Decompensated CHF: Progressive dyspnea (shortness of breath), "
            "orthopnoea (breathlessness lying flat), paroxysmal nocturnal dyspnoea, bilateral leg oedema, "
            "fatigue, and reduced exercise tolerance. "
            "Pulmonary oedema is life-threatening and requires urgent IV diuresis. "
            "Underlying causes: ischaemic heart disease, hypertension, valvular disease."
        ),
        "metadata": {
            "condition": "Acute Heart Failure",
            "urgency": "critical",
            "specialist": "cardiologist",
            "icd10": "I50",
            "keywords": "shortness of breath, leg swelling, cannot lie flat, heart failure, oedema",
        },
    },

    # ─── Neurology ─────────────────────────────────────────────────────────────
    {
        "text": (
            "Ischaemic Stroke: Sudden onset of unilateral facial droop, arm weakness, leg weakness, "
            "slurred speech (dysarthria), vision loss, or severe headache. "
            "FAST acronym: Face drooping, Arm weakness, Speech difficulty, Time to call 911. "
            "IV tPA (thrombolysis) must be given within 4.5 hours of onset. "
            "Risk factors: hypertension, diabetes, AFib, smoking, hypercholesterolaemia."
        ),
        "metadata": {
            "condition": "Ischaemic Stroke",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I63",
            "keywords": "face drooping, arm weakness, speech slurred, FAST, stroke, facial droop",
        },
    },
    {
        "text": (
            "Transient Ischaemic Attack (TIA / Mini-Stroke): Brief episode of neurological dysfunction "
            "similar to stroke (face droop, arm weakness, speech difficulty, vision change) that fully "
            "resolves within 24 hours. Often lasts minutes. "
            "TIA is a strong predictor of full stroke — 10% risk of stroke within 48 hours. "
            "Requires urgent investigation (MRI brain, carotid Doppler, ECG, antiplatelet therapy)."
        ),
        "metadata": {
            "condition": "TIA",
            "urgency": "critical",
            "specialist": "neurologist",
            "icd10": "G45",
            "keywords": "brief weakness, resolved numbness, speech, mini stroke, TIA",
        },
    },
    {
        "text": (
            "Bacterial Meningitis: Sudden severe headache, neck stiffness (nuchal rigidity), fever, "
            "photophobia (light sensitivity), phonophobia, altered consciousness. "
            "Non-blanching petechial or purpuric rash suggests meningococcal septicaemia — medical emergency. "
            "Kernig's sign and Brudzinski's sign positive. Requires urgent LP and empirical IV antibiotics "
            "(ceftriaxone + dexamethasone). Do not delay antibiotics for LP if patient is deteriorating."
        ),
        "metadata": {
            "condition": "Bacterial Meningitis",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "G00",
            "keywords": "severe headache, neck stiffness, fever, rash, photophobia, meningitis",
        },
    },
    {
        "text": (
            "Subarachnoid Haemorrhage (SAH): Sudden, explosive 'thunderclap' headache — the worst headache "
            "of the patient's life. Onset is typically instantaneous. May be associated with loss of "
            "consciousness, vomiting, photophobia, neck stiffness. "
            "Caused by rupture of intracranial aneurysm. Requires urgent CT head + LP. "
            "High mortality if untreated. Neurosurgical emergency."
        ),
        "metadata": {
            "condition": "Subarachnoid Haemorrhage",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I60",
            "keywords": "thunderclap headache, worst headache of life, sudden headache, aneurysm, SAH",
        },
    },
    {
        "text": (
            "Migraine: Unilateral throbbing headache of moderate to severe intensity. "
            "Often preceded by aura (visual disturbance — zigzag lines, scotoma, or sensory changes). "
            "Associated with nausea, vomiting, photophobia, phonophobia. "
            "Lasts 4–72 hours. Not life-threatening but debilitating. "
            "Treatment: triptans, NSAIDs, antiemetics, dark quiet room."
        ),
        "metadata": {
            "condition": "Migraine",
            "urgency": "routine",
            "specialist": "neurologist",
            "icd10": "G43",
            "keywords": "throbbing headache, unilateral, aura, nausea, light sensitive, migraine",
        },
    },
    {
        "text": (
            "Seizure / Epilepsy: Sudden involuntary movements, muscle rigidity, jerking (tonic-clonic), "
            "staring spells (absence), automatisms, or loss of consciousness. "
            "Post-ictal confusion follows. Status epilepticus (> 5 min) is a medical emergency. "
            "First seizure requires urgent workup (CT, MRI, EEG). "
            "Fever-provoked seizures in children (febrile seizures) are usually benign."
        ),
        "metadata": {
            "condition": "Seizure",
            "urgency": "critical",
            "specialist": "neurologist",
            "icd10": "G40",
            "keywords": "seizure, convulsion, jerking, shaking, loss of consciousness, epilepsy",
        },
    },

    # ─── Respiratory ───────────────────────────────────────────────────────────
    {
        "text": (
            "Acute Severe Asthma: Wheezing, cough, chest tightness, and progressive dyspnea. "
            "Unable to complete sentences. Silent chest, use of accessory muscles, cyanosis signal "
            "life-threatening exacerbation. Triggers: allergens, cold air, exercise, URTI, NSAIDs. "
            "Treatment: salbutamol nebulisers, ipratropium, IV magnesium, systemic steroids. "
            "Severe cases require ICU admission."
        ),
        "metadata": {
            "condition": "Acute Severe Asthma",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "J45",
            "keywords": "wheezing, breathlessness, chest tight, asthma, inhaler, cannot breathe",
        },
    },
    {
        "text": (
            "Pneumonia: Fever, productive cough (purulent sputum), dyspnea, pleuritic chest pain, "
            "and reduced breath sounds with dullness to percussion over affected lobe. "
            "Community-acquired pneumonia (CAP) typically caused by Streptococcus pneumoniae. "
            "CXR shows consolidation. Severity scored with CURB-65. "
            "Treatment: amoxicillin for mild CAP; hospitalisation for CURB-65 ≥ 2."
        ),
        "metadata": {
            "condition": "Pneumonia",
            "urgency": "moderate",
            "specialist": "general_practitioner",
            "icd10": "J18",
            "keywords": "fever, cough, productive cough, chest pain, breathing difficulty, pneumonia",
        },
    },
    {
        "text": (
            "COPD Exacerbation: Worsening dyspnea, increased sputum production, change in sputum colour "
            "(yellow/green), and increased cough in a patient with known COPD. "
            "Triggers: respiratory infections, air pollution. "
            "May require controlled oxygen therapy (target SpO2 88–92%), bronchodilators, steroids, antibiotics. "
            "Severe exacerbations with hypercapnia may need NIV (BiPAP)."
        ),
        "metadata": {
            "condition": "COPD Exacerbation",
            "urgency": "moderate",
            "specialist": "pulmonologist",
            "icd10": "J44",
            "keywords": "COPD, emphysema, worsening breathlessness, green sputum, smoking history",
        },
    },
    {
        "text": (
            "Tension Pneumothorax: Sudden severe pleuritic chest pain and progressive breathlessness. "
            "Tracheal deviation away from affected side, absent breath sounds, hypotension, and raised JVP "
            "— clinical emergency. Do not wait for CXR — needle decompression immediately. "
            "Occurs spontaneously (tall thin young males) or after trauma/central line insertion."
        ),
        "metadata": {
            "condition": "Tension Pneumothorax",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "J93",
            "keywords": "sudden chest pain, breathlessness, one-sided, collapsed lung, pneumothorax",
        },
    },

    # ─── Abdominal ─────────────────────────────────────────────────────────────
    {
        "text": (
            "Acute Appendicitis: Periumbilical pain migrating to the right iliac fossa (McBurney's point). "
            "Associated with fever, anorexia, nausea, and vomiting. Rebound tenderness, Rovsing's sign. "
            "Raised WBC and CRP. CT abdomen is the gold standard. "
            "Treatment: urgent appendicectomy. Perforated appendix is a surgical emergency with high mortality."
        ),
        "metadata": {
            "condition": "Appendicitis",
            "urgency": "critical",
            "specialist": "general_surgeon",
            "icd10": "K35",
            "keywords": "right side abdominal pain, lower right pain, nausea, fever, appendix",
        },
    },
    {
        "text": (
            "Acute Pancreatitis: Severe epigastric pain radiating to the back, worse lying flat, "
            "improved leaning forward. Nausea, vomiting, fever. "
            "Causes: gallstones (50%), alcohol (30%), medications. "
            "Raised serum lipase and amylase (> 3x ULN). CT for severity grading. "
            "Haemorrhagic pancreatitis (Grey-Turner's and Cullen's signs) is life-threatening."
        ),
        "metadata": {
            "condition": "Acute Pancreatitis",
            "urgency": "critical",
            "specialist": "gastroenterologist",
            "icd10": "K85",
            "keywords": "epigastric pain, back pain, radiating to back, alcohol, gallstones, pancreatitis",
        },
    },
    {
        "text": (
            "Acute Cholecystitis: Right upper quadrant pain that radiates to the right shoulder (referred). "
            "Positive Murphy's sign. Fever, nausea, vomiting. Jaundice if bile duct involved (choledocholithiasis). "
            "Ultrasound shows gallstones and gallbladder wall thickening. "
            "Treatment: IV antibiotics, analgesia, and cholecystectomy (urgent or elective)."
        ),
        "metadata": {
            "condition": "Acute Cholecystitis",
            "urgency": "moderate",
            "specialist": "general_surgeon",
            "icd10": "K81",
            "keywords": "right upper quadrant pain, right shoulder pain, gallbladder, jaundice, fatty food",
        },
    },
    {
        "text": (
            "Bowel Obstruction: Colicky abdominal pain, abdominal distension, vomiting (bilious or faeculent), "
            "and absolute constipation (no flatus or faeces). "
            "Small bowel obstruction often from adhesions or hernia. "
            "Large bowel obstruction from colorectal cancer, volvulus, or diverticular disease. "
            "AXR shows dilated loops of bowel. CT abdomen for cause. Strangulation = surgical emergency."
        ),
        "metadata": {
            "condition": "Bowel Obstruction",
            "urgency": "critical",
            "specialist": "general_surgeon",
            "icd10": "K56",
            "keywords": "bloating, distension, vomiting, constipation, no bowel movement, intestinal obstruction",
        },
    },
    {
        "text": (
            "Ruptured Abdominal Aortic Aneurysm (AAA): Sudden severe central or back pain with haemodynamic "
            "shock (hypotension, tachycardia, pallor). Pulsatile epigastric mass may be palpable. "
            "Triad: shock + abdominal pain + pulsatile mass. 90% mortality if untreated. "
            "Urgent CT if haemodynamically stable; straight to theatre if unstable. "
            "Risk factors: male, > 65, smoking, hypertension, family history."
        ),
        "metadata": {
            "condition": "Ruptured AAA",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "I71.3",
            "keywords": "sudden severe back pain, collapse, pulsatile mass, shock, aortic aneurysm",
        },
    },

    # ─── Systemic / Endocrine ───────────────────────────────────────────────────
    {
        "text": (
            "Sepsis / Septic Shock: Systemic infection with organ dysfunction. "
            "Criteria: temperature > 38.3°C or < 36°C, heart rate > 90, respiratory rate > 20, "
            "altered mental status, hypotension (SBP < 90 despite fluids). "
            "Source: pneumonia, UTI, abdominal sepsis, meningitis. "
            "Sepsis Six bundle: high-flow O2, blood cultures, IV antibiotics within 1 hour, "
            "IV fluids, lactate, urine output monitoring. ICU for septic shock."
        ),
        "metadata": {
            "condition": "Sepsis",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "A41",
            "keywords": "fever, confusion, low blood pressure, infection, sepsis, shaking, rigors",
        },
    },
    {
        "text": (
            "Anaphylaxis: Severe systemic allergic reaction. Urticaria, angioedema (lip/tongue swelling), "
            "bronchospasm (wheeze), stridor, hypotension, and loss of consciousness. "
            "Triggers: bee stings, nuts, shellfish, medications (penicillin, NSAIDs). "
            "IM epinephrine (adrenaline) 0.5mg is first-line — administer immediately. "
            "IV antihistamines and steroids adjunctive. Observe for biphasic reaction."
        ),
        "metadata": {
            "condition": "Anaphylaxis",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "T78.2",
            "keywords": "allergic reaction, lip swelling, tongue swelling, throat closing, hives, anaphylaxis, epipen",
        },
    },
    {
        "text": (
            "Diabetic Ketoacidosis (DKA): Nausea, vomiting, abdominal pain, polyuria, polydipsia, "
            "fruity/acetone breath, Kussmaul breathing (deep rapid respirations), altered consciousness. "
            "Blood glucose > 11 mmol/L, ketones in urine/blood, metabolic acidosis. "
            "Occurs in T1DM (and occasionally T2DM). Precipitant: infection, missed insulin. "
            "Treatment: IV fluid resuscitation, fixed-rate insulin infusion, electrolyte replacement."
        ),
        "metadata": {
            "condition": "DKA",
            "urgency": "critical",
            "specialist": "endocrinologist",
            "icd10": "E10.1",
            "keywords": "diabetes, high blood sugar, vomiting, fruity breath, DKA, ketoacidosis",
        },
    },
    {
        "text": (
            "Hypoglycaemia: Blood glucose < 4 mmol/L. Symptoms: tremor, sweating, palpitations, anxiety "
            "(autonomic); confusion, drowsiness, seizures, coma (neuroglycopaenic). "
            "Common in diabetics on insulin or sulfonylureas. "
            "If conscious: 15–20g fast-acting carbohydrates (glucose tablets, juice). "
            "If unconscious: IV 50mL of 50% dextrose or IM glucagon."
        ),
        "metadata": {
            "condition": "Hypoglycaemia",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "E16.0",
            "keywords": "low blood sugar, shaking, sweating, confused, diabetic, hypoglycemia",
        },
    },

    # ─── Musculoskeletal / DVT ─────────────────────────────────────────────────
    {
        "text": (
            "Deep Vein Thrombosis (DVT): Unilateral leg swelling, redness, warmth, and pain in the calf or thigh. "
            "Wells score used to assess probability. D-dimer elevated. Ultrasound (duplex) confirms. "
            "Risk: long-haul flights, surgery, immobility, malignancy, OCP, pregnancy. "
            "Treatment: anticoagulation (LMWH, then DOACs). Risk of embolisation to pulmonary circulation (PE)."
        ),
        "metadata": {
            "condition": "DVT",
            "urgency": "moderate",
            "specialist": "vascular_surgeon",
            "icd10": "I80",
            "keywords": "leg swelling, calf pain, warm red leg, DVT, deep vein thrombosis, flight",
        },
    },
    {
        "text": (
            "Musculoskeletal Back Pain (Non-specific): Localised lower back pain, often worsened by movement, "
            "improved with rest. No neurological features. Onset often after lifting or twisting. "
            "Red flags for serious pathology: nocturnal pain, weight loss, age > 50, history of cancer, "
            "IV drug use, fever, bladder/bowel dysfunction (suggests cauda equina). "
            "Treatment: analgesia (paracetamol, NSAIDs), physiotherapy, early mobilisation."
        ),
        "metadata": {
            "condition": "Non-specific Back Pain",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "M54.5",
            "keywords": "back pain, lower back, lumbar, muscle ache, back spasm",
        },
    },
    {
        "text": (
            "Cauda Equina Syndrome: Lower back pain with bilateral leg weakness, saddle anaesthesia "
            "(numbness around perineum, inner thighs), and urinary retention or faecal incontinence. "
            "Surgical emergency — irreversible neurological damage if decompression delayed > 48 hours. "
            "MRI lumbar spine urgently. Caused by large central disc herniation."
        ),
        "metadata": {
            "condition": "Cauda Equina Syndrome",
            "urgency": "critical",
            "specialist": "neurosurgeon",
            "icd10": "G83.4",
            "keywords": "back pain, leg weakness, cannot urinate, saddle numbness, cauda equina, incontinence",
        },
    },

    # ─── Urology ───────────────────────────────────────────────────────────────
    {
        "text": (
            "Renal Colic (Ureteric Stone): Sudden severe colicky loin-to-groin pain, often the worst pain "
            "the patient has experienced. Haematuria (blood in urine), nausea, vomiting. "
            "Patient cannot find a comfortable position (writhes in pain — unlike peritonitis). "
            "CT KUB is diagnostic. Treatment: NSAIDs (diclofenac) and IV morphine for pain; "
            "alpha-blockers to facilitate stone passage; urological intervention if stone > 10mm."
        ),
        "metadata": {
            "condition": "Renal Colic",
            "urgency": "moderate",
            "specialist": "urologist",
            "icd10": "N23",
            "keywords": "loin pain, flank pain, blood in urine, kidney stone, groin pain, renal colic",
        },
    },
    {
        "text": (
            "Urinary Tract Infection (UTI): Dysuria (pain on urination), urinary frequency, urgency, "
            "and haematuria. Lower UTI (cystitis): suprapubic pain. "
            "Upper UTI (pyelonephritis): loin pain, fever, rigors, vomiting — requires IV antibiotics. "
            "Common in women. Dipstick shows nitrites and leucocytes. "
            "Recurrent UTIs in men warrant urological investigation."
        ),
        "metadata": {
            "condition": "UTI / Pyelonephritis",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "N39.0",
            "keywords": "burning urination, frequent urination, painful urination, UTI, bladder infection",
        },
    },

    # ─── Psychiatric ───────────────────────────────────────────────────────────
    {
        "text": (
            "Panic Attack (mimics cardiac emergency): Sudden onset of palpitations, chest tightness, "
            "shortness of breath, dizziness, paraesthesia (tingling in hands/face), trembling, "
            "sweating, fear of dying. Peaks within 10 minutes. No ECG abnormality. "
            "Important: exclude cardiac cause before diagnosing. "
            "Treatment: reassurance, controlled breathing, CBT, SSRI for recurrent panic disorder."
        ),
        "metadata": {
            "condition": "Panic Attack",
            "urgency": "routine",
            "specialist": "psychiatrist",
            "icd10": "F41.0",
            "keywords": "palpitations, chest tight, breathless, anxiety, tingling, fear of dying, panic",
        },
    },

    # ─── ENT / Airway ───────────────────────────────────────────────────────────
    {
        "text": (
            "Epiglottitis: Rapidly progressive sore throat, dysphagia (difficulty swallowing), drooling, "
            "stridor (high-pitched breathing sound), and muffled 'hot potato' voice. "
            "Tripod posturing. Do not examine throat — may precipitate complete airway obstruction. "
            "Anaesthetist + ENT urgently. IV ceftriaxone. Rare since Hib vaccination."
        ),
        "metadata": {
            "condition": "Epiglottitis",
            "urgency": "critical",
            "specialist": "emergency_medicine",
            "icd10": "J05.1",
            "keywords": "sore throat, drooling, difficulty swallowing, stridor, throat swelling, epiglottitis",
        },
    },

    # ─── General / Viral ────────────────────────────────────────────────────────
    {
        "text": (
            "Viral Upper Respiratory Tract Infection (URTI / Common Cold): "
            "Runny nose, nasal congestion, sore throat, cough, low-grade fever, fatigue, and myalgia. "
            "Self-limiting — resolves in 7–10 days. No antibiotics required. "
            "Management: rest, hydration, paracetamol, decongestants. "
            "Seek review if symptoms worsen after 7 days, high fever persists, or earache develops."
        ),
        "metadata": {
            "condition": "Viral URTI / Common Cold",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "J06",
            "keywords": "runny nose, cold, cough, sore throat, mild fever, congestion",
        },
    },
    {
        "text": (
            "Influenza (Flu): Sudden onset of high fever (> 38.5°C), severe myalgia (muscle aches), "
            "headache, rigors, dry cough, and malaise. Unlike common cold, onset is abrupt and systemic. "
            "Complications: bacterial pneumonia, encephalitis, myocarditis. "
            "High-risk groups (elderly, immunocompromised, pregnant) may need oseltamivir (Tamiflu). "
            "Annual influenza vaccination recommended."
        ),
        "metadata": {
            "condition": "Influenza",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "J10",
            "keywords": "flu, high fever, muscle ache, body ache, sudden fever, influenza",
        },
    },
    {
        "text": (
            "Gastroenteritis: Nausea, vomiting, diarrhoea, and abdominal cramps. Often viral (norovirus, rotavirus). "
            "Bacterial causes: Salmonella, Campylobacter, E. coli (food poisoning). "
            "Key concern: dehydration — especially dangerous in elderly and children. "
            "Oral rehydration therapy is mainstay. Blood in stool or high fever warrants stool culture. "
            "Usually self-limiting within 48–72 hours."
        ),
        "metadata": {
            "condition": "Gastroenteritis",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "A09",
            "keywords": "vomiting, diarrhoea, stomach cramps, food poisoning, nausea, gastro",
        },
    },
    {
        "text": (
            "Tension Headache: Bilateral pressing or tightening headache, like a band around the head. "
            "Mild to moderate intensity. Not worsened by activity. No nausea or vomiting (unlike migraine). "
            "Associated with stress, poor posture, eye strain, dehydration. "
            "Treatment: paracetamol, NSAIDs, relaxation techniques. Frequent use of analgesics causes "
            "medication-overuse headache."
        ),
        "metadata": {
            "condition": "Tension Headache",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "G44.2",
            "keywords": "headache, band around head, pressure headache, bilateral headache, tension",
        },
    },
    {
        "text": (
            "Allergic Rhinitis / Hay Fever: Sneezing, nasal itch, watery rhinorrhoea, nasal congestion, "
            "and conjunctivitis (red, itchy, watery eyes). Seasonal (pollen) or perennial (dust mites, pet dander). "
            "Treatment: intranasal corticosteroids (first-line), antihistamines, decongestants. "
            "Allergen immunotherapy for refractory cases."
        ),
        "metadata": {
            "condition": "Allergic Rhinitis",
            "urgency": "routine",
            "specialist": "general_practitioner",
            "icd10": "J30",
            "keywords": "sneezing, runny nose, itchy eyes, hay fever, allergies, seasonal",
        },
    },
]

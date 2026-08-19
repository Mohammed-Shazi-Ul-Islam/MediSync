"""
app/services/specialist_kb.py

Module 03 — Specialist Router: Specialist Profile Knowledge Base.

This is the ChromaDB embedding corpus for the *semantic routing layer*.
It is intentionally separate from medical_kb.py (condition-centric) —
these documents are SPECIALIST-centric: each entry describes what a particular
type of specialist handles, their typical patient presentations, and what
differentiates them from adjacent specialties.

Design rationale:
  - Rich, dense prose (~200 words per profile) gives the embedding model
    enough signal to discriminate between similar specialties
    (e.g. neurologist vs. neurosurgeon vs. emergency_medicine for headache cases).
  - Each document includes 'boundary notes' — explicit descriptions of when
    a case should escalate to a different specialist — so the embedding
    captures the specialist's scope of practice clearly.
  - Keywords in each text are calibrated against medical_kb.py metadata fields
    so the two knowledge bases are semantically consistent.

Collection: "specialist_profiles" (configured via CHROMA_SPECIALIST_COLLECTION_NAME)
"""

from __future__ import annotations

SPECIALIST_KB: list[dict] = [

    # ── Emergency Medicine ─────────────────────────────────────────────────────
    {
        "text": (
            "Emergency Medicine Physician — handles all immediately life-threatening presentations "
            "requiring emergency department care. Core competencies: resuscitation, airway management, "
            "trauma, cardiac arrest, stroke (acute), STEMI, PE, aortic dissection, anaphylaxis, "
            "septic shock, DKA, hypoglycaemic coma, meningococcal disease, tension pneumothorax, "
            "subarachnoid haemorrhage, major trauma, burns, and toxicology. "
            "This specialist is the first responder for any patient presenting with: chest pain with "
            "haemodynamic instability, sudden severe headache (thunderclap), face droop + arm weakness, "
            "loss of consciousness, anaphylaxis (throat swelling, stridor, hypotension), or signs of "
            "systemic sepsis. Emergency physicians perform rapid diagnostic workup (ECG, CT, bloods), "
            "initiate stabilising treatment, and then hand off to inpatient teams. "
            "Boundary: once stabilised, cardiology takes over for STEMI/NSTEMI, neurology for stroke, "
            "surgery for ruptured AAA or perforated viscus. Triage urgency: critical only."
        ),
        "metadata": {
            "specialist": "emergency_medicine",
            "urgency_affinity": "critical",
            "display_name": "Emergency Medicine Physician",
        },
    },

    # ── Cardiology ─────────────────────────────────────────────────────────────
    {
        "text": (
            "Cardiologist — specialist in diseases of the heart and cardiovascular system. "
            "Handles: coronary artery disease (stable angina, NSTEMI post-stabilisation), "
            "atrial fibrillation and other arrhythmias (palpitations, racing heart, flutter), "
            "heart failure (dyspnoea, leg oedema, orthopnoea), valvular heart disease, "
            "cardiomyopathies, hypertension management, and pre-operative cardiac assessment. "
            "Typical presentations: chest tightness on exertion, palpitations, irregular heartbeat, "
            "dyspnoea on minimal exertion, ankle swelling, and syncope with cardiac aetiology. "
            "Diagnostic tools: echocardiogram, Holter monitor, stress testing, cardiac catheterisation, "
            "coronary CT angiography. Electrophysiologists (a cardiologist subspecialty) manage "
            "complex arrhythmias and perform ablation. Interventional cardiologists perform PCI. "
            "Boundary: acute STEMI → emergency medicine first, then interventional cardiology; "
            "routine hypertension → GP; structural defects needing surgery → cardiac surgeon. "
            "Urgency affinity: critical (unstable angina, decompensated heart failure), "
            "moderate (new-onset AF, chest pain under investigation), routine (stable angina follow-up)."
        ),
        "metadata": {
            "specialist": "cardiologist",
            "urgency_affinity": "moderate",
            "display_name": "Cardiologist",
        },
    },

    # ── Neurology ──────────────────────────────────────────────────────────────
    {
        "text": (
            "Neurologist — specialist in disorders of the brain, spinal cord, peripheral nerves, "
            "and neuromuscular system. Handles: ischaemic stroke (post-acute), TIA (mini-stroke), "
            "epilepsy and seizure disorders, migraine and headache syndromes, multiple sclerosis, "
            "Parkinson's disease, peripheral neuropathy, Guillain-Barré syndrome, myasthenia gravis, "
            "dementia and cognitive decline, essential tremor, and vertigo (central causes). "
            "Typical presentations: recurring severe headaches, unilateral weakness or numbness, "
            "speech difficulty, visual disturbance, seizures (first episode or uncontrolled), "
            "memory loss, gait disturbance, and tingling or burning sensations in limbs. "
            "Diagnostic tools: MRI brain/spine, EEG, nerve conduction studies, lumbar puncture. "
            "Boundary: acute stroke → emergency medicine first; surgical conditions (tumour, disc) → "
            "neurosurgeon; psychiatric symptoms → psychiatry; ENT-related vertigo → ENT. "
            "Urgency affinity: critical (seizure, TIA, acute stroke follow-up), "
            "moderate (new neurological deficit), routine (migraine, tremor)."
        ),
        "metadata": {
            "specialist": "neurologist",
            "urgency_affinity": "moderate",
            "display_name": "Neurologist",
        },
    },

    # ── Neurosurgery ───────────────────────────────────────────────────────────
    {
        "text": (
            "Neurosurgeon — surgical specialist for conditions of the central and peripheral nervous "
            "system requiring operative intervention. Handles: intracranial haemorrhage (SAH, subdural, "
            "epidural haematoma), brain tumours, spinal cord compression, cauda equina syndrome, "
            "lumbar and cervical disc herniation causing neurological deficit, spinal stenosis, "
            "Chiari malformation, hydrocephalus, and trigeminal neuralgia. "
            "Key surgical triggers: sudden severe headache from aneurysm rupture (SAH), progressive "
            "neurological deficits from spinal cord compression, urinary retention with saddle "
            "anaesthesia (cauda equina — surgical emergency), and space-occupying brain lesions. "
            "Typical presentations: thunderclap headache, bilateral leg weakness, loss of bladder "
            "or bowel control, arm/leg weakness from spinal cord compression, and head trauma with "
            "intracranial bleed. "
            "Boundary: non-surgical spinal pain → orthopaedics or physiotherapy; medical neurological "
            "disease → neurology; acute haemorrhage in ER → emergency medicine first, then neurosurgery. "
            "Urgency affinity: critical (cauda equina, SAH, acute intracranial bleed)."
        ),
        "metadata": {
            "specialist": "neurosurgeon",
            "urgency_affinity": "critical",
            "display_name": "Neurosurgeon",
        },
    },

    # ── Pulmonology ────────────────────────────────────────────────────────────
    {
        "text": (
            "Pulmonologist (Respiratory Physician) — specialist in diseases of the lungs and respiratory "
            "system. Handles: chronic obstructive pulmonary disease (COPD) management and exacerbations, "
            "asthma (follow-up, refractory cases), interstitial lung disease (ILD), pulmonary fibrosis, "
            "lung cancer investigation, pleural disease (effusion, empyema), obstructive sleep apnoea, "
            "and sarcoidosis. "
            "Typical presentations: progressive breathlessness on exertion, chronic productive cough, "
            "wheezing unresponsive to inhalers, haemoptysis (blood in cough), night-time hypoxaemia, "
            "weight loss with respiratory symptoms, and recurrent chest infections. "
            "Diagnostic tools: spirometry, HRCT chest, bronchoscopy, sleep study, arterial blood gas. "
            "Boundary: acute severe asthma → emergency medicine; pneumonia needing admission → general "
            "medicine or EM; PE → emergency medicine then haematology/respiratory; lung surgery → "
            "cardiothoracic surgery. "
            "Urgency affinity: moderate (COPD exacerbation, new haemoptysis), routine (stable COPD review)."
        ),
        "metadata": {
            "specialist": "pulmonologist",
            "urgency_affinity": "moderate",
            "display_name": "Pulmonologist",
        },
    },

    # ── Gastroenterology ───────────────────────────────────────────────────────
    {
        "text": (
            "Gastroenterologist — specialist in digestive system disorders including the oesophagus, "
            "stomach, small intestine, large intestine, liver, gallbladder, and pancreas. "
            "Handles: inflammatory bowel disease (Crohn's, ulcerative colitis), irritable bowel "
            "syndrome, GERD (acid reflux), peptic ulcer disease, coeliac disease, liver cirrhosis, "
            "hepatitis, pancreatitis (follow-up), GI bleeding (haematemesis, melaena, rectal bleeding), "
            "colorectal cancer screening and polyp removal, and dysphagia workup. "
            "Typical presentations: persistent abdominal pain, blood in stool, dark tarry stools, "
            "vomiting blood, jaundice, altered bowel habits, unexplained weight loss with GI symptoms, "
            "epigastric pain, bloating, and dysphagia. "
            "Diagnostic tools: upper and lower endoscopy (gastroscopy, colonoscopy), CT abdomen, MRCP, "
            "liver biopsy, capsule endoscopy. "
            "Boundary: acute GI bleeding → emergency medicine; surgical abdomen (perforation, "
            "obstruction) → general surgery; pancreatitis (acute critical) → emergency medicine first. "
            "Urgency affinity: critical (acute GI bleed), moderate (pancreatitis follow-up, new jaundice)."
        ),
        "metadata": {
            "specialist": "gastroenterologist",
            "urgency_affinity": "moderate",
            "display_name": "Gastroenterologist",
        },
    },

    # ── General Surgery ────────────────────────────────────────────────────────
    {
        "text": (
            "General Surgeon — specialist performing operative management of abdominal and soft-tissue "
            "conditions. Core surgical domains: appendicitis (appendicectomy), cholecystitis "
            "(cholecystectomy), bowel obstruction, perforated viscus, hernia repair, colorectal surgery, "
            "breast surgery, and soft-tissue procedures (abscess drainage, wound debridement). "
            "Typical presentations requiring surgical referral: right iliac fossa pain (possible "
            "appendicitis), right upper quadrant pain with fever and positive Murphy's sign "
            "(cholecystitis), abdominal distension with vomiting and absolute constipation (obstruction), "
            "generalised peritonism (perforation), and incarcerated hernia. "
            "Diagnostic approach: clinical examination, bloods (WBC, CRP, lipase), CT abdomen, ultrasound. "
            "Boundary: ruptured AAA → vascular surgery + EM; GI malignancy follow-up → gastroenterology; "
            "endoscopic procedures → gastroenterology; urology → urologist. "
            "Urgency affinity: critical (appendicitis, bowel obstruction, perforation), "
            "moderate (cholecystitis, elective hernia)."
        ),
        "metadata": {
            "specialist": "general_surgeon",
            "urgency_affinity": "critical",
            "display_name": "General Surgeon",
        },
    },

    # ── Endocrinology ──────────────────────────────────────────────────────────
    {
        "text": (
            "Endocrinologist — specialist in hormonal and metabolic disorders. Key areas: "
            "diabetes mellitus (Type 1, Type 2) management — including complications and insulin "
            "regimen optimisation; thyroid disorders (hypothyroidism, hyperthyroidism, thyroid nodules); "
            "adrenal disease (Cushing's syndrome, Addison's disease, phaeochromocytoma); "
            "pituitary disorders; osteoporosis and calcium metabolism; polycystic ovary syndrome (PCOS); "
            "and obesity management. "
            "Typical presentations: unexplained weight loss or gain, fatigue, polydipsia (excessive "
            "thirst), polyuria, recurrent hypoglycaemia, heat or cold intolerance, hair loss, "
            "moon face, buffalo hump, and hyperpigmentation. "
            "Boundary: DKA and HHS → emergency medicine first; simple T2DM → GP; thyroid cancer → "
            "oncology + endocrinology; hypoglycaemia in ER → emergency medicine. "
            "Urgency affinity: moderate (poorly controlled diabetes, new thyroid disease), "
            "routine (stable endocrine follow-up)."
        ),
        "metadata": {
            "specialist": "endocrinologist",
            "urgency_affinity": "moderate",
            "display_name": "Endocrinologist",
        },
    },

    # ── Urology ────────────────────────────────────────────────────────────────
    {
        "text": (
            "Urologist — specialist in urinary tract and male reproductive system conditions. "
            "Handles: nephrolithiasis (kidney stones / renal colic), urinary tract infections (UTI) "
            "with urological complications, haematuria (blood in urine) investigation, bladder cancer, "
            "renal cell carcinoma, prostate disease (BPH, prostate cancer), urinary incontinence, "
            "urethral stricture, male infertility, testicular torsion, and erectile dysfunction. "
            "Typical presentations: severe loin-to-groin colicky pain (renal colic), frank haematuria, "
            "difficulty urinating, incomplete bladder emptying, urinary retention, recurrent UTIs in "
            "males, scrotal pain or swelling, and painless haematuria (red flag for malignancy). "
            "Diagnostic tools: CT KUB, cystoscopy, urine cytology, PSA, renal ultrasound, urodynamics. "
            "Boundary: uncomplicated UTI in women → GP; acute pyelonephritis → GP or general medicine; "
            "testicular torsion → emergency surgery; renal trauma → urology + emergency. "
            "Urgency affinity: moderate (renal colic, haematuria workup), routine (BPH, stone follow-up)."
        ),
        "metadata": {
            "specialist": "urologist",
            "urgency_affinity": "moderate",
            "display_name": "Urologist",
        },
    },

    # ── Vascular Surgery ───────────────────────────────────────────────────────
    {
        "text": (
            "Vascular Surgeon — specialist in diseases of the arteries, veins, and lymphatic system, "
            "both interventional and operative. Handles: peripheral arterial disease (claudication, "
            "critical limb ischaemia), aortic aneurysm (AAA) — surveillance and elective/emergency "
            "repair, deep vein thrombosis (DVT) management, varicose veins, carotid artery stenosis "
            "(stroke prevention), and acute limb ischaemia. "
            "Typical presentations: painful, cold, pale, pulseless limb (acute arterial occlusion — "
            "emergency), unilateral leg swelling with pain and warmth (DVT), pulsatile abdominal mass, "
            "buttock or calf pain on walking (claudication), and non-healing foot ulcers in diabetics. "
            "Diagnostic tools: Doppler ultrasound (duplex), CT angiography, ankle-brachial pressure index. "
            "Boundary: ruptured AAA → emergency medicine + emergency vascular surgery; "
            "PE from DVT → respiratory / emergency medicine; uncomplicated DVT → anticoagulation by GP. "
            "Urgency affinity: critical (ruptured AAA, acute limb ischaemia), "
            "moderate (DVT, symptomatic AAA), routine (varicose veins)."
        ),
        "metadata": {
            "specialist": "vascular_surgeon",
            "urgency_affinity": "moderate",
            "display_name": "Vascular Surgeon",
        },
    },

    # ── Psychiatry ─────────────────────────────────────────────────────────────
    {
        "text": (
            "Psychiatrist — specialist in mental, emotional, and behavioural disorders. Handles: "
            "panic disorder and anxiety disorders, major depressive disorder, bipolar affective disorder, "
            "schizophrenia and psychotic disorders, obsessive-compulsive disorder (OCD), PTSD, "
            "eating disorders, substance use disorders, and personality disorders. "
            "Typical presentations that may mimic medical emergencies: panic attacks (palpitations, "
            "chest tightness, shortness of breath, tingling — must exclude cardiac cause first), "
            "somatoform disorders, conversion disorder, and acute psychotic breaks. "
            "Also evaluates: suicidal ideation and risk, self-harm, acute confusional states with "
            "psychiatric aetiology, and medically unexplained physical symptoms. "
            "Boundary: panic attack — always exclude cardiac and respiratory causes first (ECG, bloods); "
            "delirium in elderly → general medicine / geriatrics; substance overdose → emergency medicine; "
            "dementia with challenging behaviour → old-age psychiatry. "
            "Urgency affinity: routine (anxiety, depression follow-up), "
            "moderate (new-onset psychosis, acute suicidal ideation requiring rapid assessment)."
        ),
        "metadata": {
            "specialist": "psychiatrist",
            "urgency_affinity": "routine",
            "display_name": "Psychiatrist",
        },
    },

    # ── General Practitioner ───────────────────────────────────────────────────
    {
        "text": (
            "General Practitioner (GP / Family Doctor) — primary care physician who handles the full "
            "breadth of non-specialist, routine, and community presentations. Core scope: upper "
            "respiratory tract infections, viral illness, influenza, common cold, gastroenteritis, "
            "urinary tract infection (uncomplicated), tension headache, allergic rhinitis (hay fever), "
            "minor musculoskeletal back pain, skin rashes, hypertension monitoring, diabetes "
            "routine review, mental health first-line management, preventive care (vaccinations, "
            "screening), and chronic disease monitoring (COPD stable, asthma reviews). "
            "GPs refer on to specialists when symptoms are persistent, unusual, or involve red flags. "
            "Typical presentations: cough and cold, sore throat, ear pain, runny nose, mild fever, "
            "headache (non-alarming), minor injuries, routine prescription refills, and preventive health. "
            "Boundary: anything with red flags (thunderclap headache, chest pain, stroke features, "
            "significant weight loss, haematuria) → specialist or ER immediately. "
            "Urgency affinity: routine (vast majority of GP presentations)."
        ),
        "metadata": {
            "specialist": "general_practitioner",
            "urgency_affinity": "routine",
            "display_name": "General Practitioner",
        },
    },

    # ── Orthopaedics ───────────────────────────────────────────────────────────
    {
        "text": (
            "Orthopaedic Surgeon (Orthopaedist) — specialist in conditions of bones, joints, "
            "muscles, tendons, ligaments, and the musculoskeletal system. Handles: fractures and "
            "dislocations (operative and non-operative), knee and hip joint replacement (osteoarthritis), "
            "sports injuries (ligament tears — ACL, meniscus), rotator cuff tears, tendinopathies, "
            "spinal surgery for disc disease (cervical/lumbar), scoliosis correction, and bone "
            "tumours. Also manages: chronic back pain with mechanical cause, shoulder impingement, "
            "carpal tunnel syndrome, and foot/ankle deformities. "
            "Typical presentations: joint pain and swelling following trauma, inability to weight-bear, "
            "deformity after injury, chronic joint pain limiting mobility, muscle weakness from "
            "peripheral nerve or structural cause, and new bone pain with deformity. "
            "Diagnostic tools: X-ray, MRI, CT scan, bone density (DEXA). "
            "Boundary: septic arthritis → orthopaedics + emergency (joint washout needed urgently); "
            "inflammatory arthropathy → rheumatology; spinal cord compression → neurosurgery. "
            "Urgency affinity: moderate (acute fracture, septic joint), routine (elective joint replacement)."
        ),
        "metadata": {
            "specialist": "orthopedist",
            "urgency_affinity": "moderate",
            "display_name": "Orthopaedic Surgeon",
        },
    },

    # ── Rheumatology ───────────────────────────────────────────────────────────
    {
        "text": (
            "Rheumatologist — specialist in autoimmune, inflammatory, and musculoskeletal diseases "
            "not requiring surgery. Core conditions: rheumatoid arthritis (swollen, warm, stiff joints "
            "in the morning), systemic lupus erythematosus (SLE — joint pain, butterfly rash, fatigue), "
            "gout and pseudogout (acute hot red swollen joint, often big toe), ankylosing spondylitis, "
            "psoriatic arthritis, polymyalgia rheumatica, vasculitis, Sjögren's syndrome, and "
            "fibromyalgia. Also manages: antiphospholipid syndrome, scleroderma, and inflammatory myopathy. "
            "Typical presentations: symmetrical small-joint polyarthritis with morning stiffness >1 hour "
            "(RA), acute monoarthritis with tophi or hyperuricaemia (gout), systemic symptoms with joint "
            "involvement (SLE, vasculitis), and elevated ESR/CRP with musculoskeletal symptoms. "
            "Diagnostic tools: rheumatoid factor, anti-CCP, ANA, ANCA, uric acid, joint aspiration. "
            "Boundary: septic joint → orthopaedics urgently; gout crisis can start at GP; "
            "renal lupus → nephrology co-management. "
            "Urgency affinity: moderate (acute gout, new RA), routine (stable autoimmune follow-up)."
        ),
        "metadata": {
            "specialist": "rheumatologist",
            "urgency_affinity": "moderate",
            "display_name": "Rheumatologist",
        },
    },

    # ── Dermatology ────────────────────────────────────────────────────────────
    {
        "text": (
            "Dermatologist — specialist in skin, hair, nail, and mucous membrane conditions. "
            "Handles: eczema (atopic dermatitis), psoriasis, acne, skin infections (cellulitis, "
            "impetigo, tinea), viral exanthems (herpes zoster / shingles), urticaria (hives), "
            "skin cancer (melanoma, BCC, SCC) screening and excision, alopecia, nail disorders, "
            "and drug rashes. Also manages: Stevens-Johnson syndrome (severe drug reaction), "
            "pemphigus vulgaris, and leg ulcer dermatological assessment. "
            "Typical presentations: rash, itching (pruritus), skin lesions or moles with changing "
            "appearance, blistering, scaling plaques, painful vesicular rash (shingles), "
            "non-healing wound, and widespread erythematous eruption. "
            "Red flags in dermatology: rapidly spreading cellulitis with fever → IV antibiotics and "
            "possible hospitalisation; suspected necrotising fasciitis → emergency surgery immediately; "
            "anaphylaxis with urticaria → emergency medicine. "
            "Boundary: cellulitis with systemic sepsis → emergency medicine or general medicine; "
            "skin manifestation of autoimmune disease → rheumatology + dermatology co-management. "
            "Urgency affinity: moderate (infected cellulitis, new suspicious mole), routine (chronic skin disease)."
        ),
        "metadata": {
            "specialist": "dermatologist",
            "urgency_affinity": "routine",
            "display_name": "Dermatologist",
        },
    },
]

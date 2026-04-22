from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class GenerationConfig:
    seed: int
    output_seed_dir: Path
    output_eval_dir: Path
    target_counts: dict[str, int]
    scenario_mix: dict[str, float]


def _load_config(config_path: Path) -> GenerationConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return GenerationConfig(
        seed=int(raw["seed"]),
        output_seed_dir=PROJECT_ROOT / str(raw["output_seed_dir"]),
        output_eval_dir=PROJECT_ROOT / str(raw["output_eval_dir"]),
        target_counts={k: int(v) for k, v in raw["target_counts"].items()},
        scenario_mix={k: float(v) for k, v in raw["scenario_mix"].items()},
    )


def _pick(rng: random.Random, items: list[str]) -> str:
    return items[rng.randrange(0, len(items))]


def _new_scenario(
    registry: list[dict],
    scenario_type: str,
    suspiciousness: str,
    description: str,
) -> str:
    sid = f"SCN_{len(registry) + 1:04d}"
    registry.append(
        {
            "scenario_id": sid,
            "scenario_type": scenario_type,
            "suspiciousness": suspiciousness,
            "description": description,
        }
    )
    return sid


def _scenario_buckets(total_people: int, mix: dict[str, float]) -> dict[str, int]:
    baseline = int(round(total_people * mix["baseline"]))
    suspicious = int(round(total_people * mix["suspicious"]))
    ambiguous = total_people - baseline - suspicious
    return {
        "baseline": max(0, baseline),
        "suspicious": max(0, suspicious),
        "ambiguous": max(0, ambiguous),
    }


def generate_dataset(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    rng = random.Random(config.seed)

    first_names = [
        "JANE", "JOHN", "MARIA", "ROBERT", "SAM", "ALAN", "PAT", "LUCY", "MIA", "NOAH",
        "ISLA", "ETHAN", "AVA", "LEO", "CHLOE", "BEN", "EMMA", "LIAM", "NORA", "ELI",
    ]
    last_names = [
        "DOE", "GARCIA", "CHEN", "LEE", "WEBB", "KIM", "MARTIN", "BROWN", "PARK",
        "WILSON", "SINGH", "RIVERA", "ZHOU", "HERNANDEZ", "KELLY",
    ]
    cities = ["BOSTON", "QUINCY", "WALTHAM", "LYNN", "CAMBRIDGE", "SOMERVILLE", "BROOKLINE"]
    street_roots = ["MAPLE", "HARBOR", "INDUSTRIAL", "COMMERCE", "UNION", "CEDAR", "FRANKLIN"]

    counts = config.target_counts
    people_n = counts["persons"]
    businesses_n = counts["businesses"]
    policies_n = counts["policies"]
    claims_n = counts["claims"]
    addresses_n = counts["addresses"]
    banks_n = counts["bank_accounts"]

    buckets = _scenario_buckets(people_n, config.scenario_mix)

    scenario_registry: list[dict] = []
    entity_scenario_map: list[dict] = []
    edge_scenario_map: list[dict] = []

    # Core entities -----------------------------------------------------------------
    people: list[dict] = []
    for i in range(people_n):
        pid = 5001 + i
        birth_year = rng.randint(1944, 2000)
        birth_month = rng.randint(1, 12)
        birth_day = rng.randint(1, 28)
        sex = _pick(rng, ["F", "M"])
        people.append(
            {
                "RES_PERSON_ID": pid,
                "FIRST_NAME": _pick(rng, first_names),
                "MIDDLE_NAME": "",
                "LAST_NAME": _pick(rng, last_names),
                "BIRTH_DATE": f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}",
                "SEX": sex,
                "SSN": f"***-**-{pid % 10000:04d}",
                "DEATH_DATE": "",
                "DECEASED_IND": "",
            }
        )

    addresses: list[dict] = []
    for i in range(addresses_n):
        aid = 9001 + i
        city = _pick(rng, cities)
        addresses.append(
            {
                "RES_ADDRESS_ID": aid,
                "ADDRESS_LINE_1": f"{100 + i} {_pick(rng, street_roots)} ST",
                "ADDRESS_LINE_2": "" if rng.random() > 0.25 else f"UNIT {rng.randint(1, 40)}",
                "ADDRESS_LINE_3": "",
                "CITY": city,
                "STATE": "MA",
                "ZIP_CODE": f"0{rng.randint(1800, 2799)}",
                "LATITUDE": round(42.2 + rng.random() * 0.3, 6),
                "LONGITUDE": round(-71.3 + rng.random() * 0.4, 6),
            }
        )

    businesses: list[dict] = []
    btypes = ["HHCA", "NH", "BILLING", "PT_CLINIC", "HOME_SERVICES"]
    for i in range(businesses_n):
        bid = 7001 + i
        businesses.append(
            {
                "RES_BUSINESS_ID": bid,
                "BUSINESS_NAME": f"{_pick(rng, ['RESOLVE', 'NORTH SHORE', 'APEX', 'HARBOR'])} CARE {i+1} LLC",
                "TAX_ID": f"{rng.randint(10, 98)}-{rng.randint(1000000, 9999999)}",
                "BUSINESS_TYPE": _pick(rng, btypes),
                "DUNS_NUMBER": str(rng.randint(100000000, 999999999)),
            }
        )

    policies: list[dict] = []
    for i in range(policies_n):
        pnum = f"POL-LTC-{10001 + i:05d}"
        issue_year = rng.randint(2010, 2025)
        policies.append(
            {
                "COMPANY_CODE": "JH",
                "POLICY_NUMBER": pnum,
                "POLICY_STATUS": "Active" if rng.random() > 0.15 else "Lapsed",
                "POLICY_SUB_STATUS": "In Good Standing" if rng.random() > 0.2 else "Payment Pending",
                "PRODUCT_CODE": _pick(rng, ["LTC_STD", "LTC_PLUS"]),
                "ISSUE_DATE": f"{issue_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "ISSUE_STATE": "MA",
                "PREMIUM_AMT": round(rng.uniform(250.0, 780.0), 2),
                "TOTAL_PREMIUM_PAID": round(rng.uniform(4000.0, 50000.0), 2),
            }
        )

    claims: list[dict] = []
    for i in range(claims_n):
        cid = f"C{9000000001 + i}"
        p = policies[i % len(policies)]
        claimant = people[rng.randrange(0, len(people))]
        year = rng.choice([2023, 2024, 2025])
        status = "OPEN" if rng.random() > 0.4 else "CLOSED"
        claims.append(
            {
                "CLAIM_ID": cid,
                "CLAIM_NUMBER": f"CLM-{year}-{10000 + i:05d}",
                "POLICY_NUMBER": p["POLICY_NUMBER"],
                "FIRST_NAME": claimant["FIRST_NAME"],
                "LAST_NAME": claimant["LAST_NAME"],
                "BIRTH_DATE": claimant["BIRTH_DATE"],
                "CLAIM_OPEN_DATE": f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "CLAIM_CLOSE_DATE": "" if status == "OPEN" else f"{year+1}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "CLAIM_STATUS_CODE": status,
                "CLAIM_VALID_IND": 1,
                "CLAIM_SYSTEM": "SYS01",
            }
        )

    banks: list[dict] = []
    for i in range(banks_n):
        bid = 8001 + i
        banks.append(
            {
                "RES_BANK_ACCOUNT_ID": bid,
                "ROUTING_NUMBER": _pick(rng, ["021000021", "011401533", "211370545"]),
                "ACCOUNT_NUMBER": f"****{rng.randint(1000, 9999)}",
            }
        )

    # Crosswalk baseline -------------------------------------------------------------
    person_address = []
    person_policy = []
    person_bank = []
    person_person = []
    business_address = []

    # locality-first base assignment
    for p in people:
        addr = addresses[rng.randrange(0, len(addresses))]
        person_address.append(
            {
                "RES_PERSON_ID": p["RES_PERSON_ID"],
                "EDGE_NAME": "LOCATED_IN",
                "EFFECTIVE_DATE": "2023-01-01",
                "IS_LATEST_ADDRESS_IND": 1,
                "RES_ADDRESS_ID": addr["RES_ADDRESS_ID"],
            }
        )

    # business addresses (few colocations by design)
    for b in businesses:
        if rng.random() < 0.33:
            p = people[rng.randrange(0, len(people))]
            p_addr = next(
                pa["RES_ADDRESS_ID"] for pa in person_address if pa["RES_PERSON_ID"] == p["RES_PERSON_ID"]
            )
            aid = p_addr
        else:
            aid = addresses[rng.randrange(0, len(addresses))]["RES_ADDRESS_ID"]
        business_address.append({"RES_BUSINESS_ID": b["RES_BUSINESS_ID"], "RES_ADDRESS_ID": aid})

    # person-policy links
    for p in people:
        pol = policies[rng.randrange(0, len(policies))]
        person_policy.append(
            {
                "RES_PERSON_ID": p["RES_PERSON_ID"],
                "EDGE_NAME": "IS_COVERED_BY",
                "EDGE_DETAIL": "",
                "EDGE_DETAIL_DSC": "",
                "POLICY_NUMBER": pol["POLICY_NUMBER"],
            }
        )
        if rng.random() < 0.08:
            pol2 = policies[rng.randrange(0, len(policies))]
            person_policy.append(
                {
                    "RES_PERSON_ID": p["RES_PERSON_ID"],
                    "EDGE_NAME": "SOLD_POLICY",
                    "EDGE_DETAIL": "WRITING_AGENT",
                    "EDGE_DETAIL_DSC": "AGENT",
                    "POLICY_NUMBER": pol2["POLICY_NUMBER"],
                }
            )

    # person-bank links
    for p in people:
        bank = banks[rng.randrange(0, len(banks))]
        person_bank.append(
            {
                "RES_BANK_ACCOUNT_ID": bank["RES_BANK_ACCOUNT_ID"],
                "EDGE_NAME": "HOLD_BY",
                "RES_PERSON_ID": p["RES_PERSON_ID"],
            }
        )

    # person-person relationships
    pp_types = ["IS_SPOUSE_OF", "IS_RELATED_TO"]
    for _ in range(max(people_n // 2, 1)):
        a, b = rng.sample(people, 2)
        person_person.append(
            {
                "RES_PERSON_ID_SRC": a["RES_PERSON_ID"],
                "EDGE_NAME": _pick(rng, pp_types),
                "EDGE_DETAIL": _pick(rng, ["SISTER", "COUSIN", "SPOUSE", "BUSINESS_PARTNER"]),
                "EDGE_DETAIL_DSC": "FAMILY",
                "RES_PERSON_ID_TGT": b["RES_PERSON_ID"],
            }
        )

    # Scenario layering --------------------------------------------------------------
    people_by_id = {p["RES_PERSON_ID"]: p for p in people}
    policy_numbers = [p["POLICY_NUMBER"] for p in policies]
    candidate_people = [p["RES_PERSON_ID"] for p in people]
    rng.shuffle(candidate_people)
    suspicious_people = set(candidate_people[: buckets["suspicious"]])
    ambiguous_people = set(candidate_people[buckets["suspicious"]: buckets["suspicious"] + buckets["ambiguous"]])
    baseline_people = set(candidate_people) - suspicious_people - ambiguous_people

    # 1) baseline world
    baseline_sid = _new_scenario(
        scenario_registry,
        "baseline_world",
        "baseline",
        "Background insured population with mostly local, sparse relationships.",
    )
    for pid in baseline_people:
        entity_scenario_map.append(
            {"entity_type": "Person", "entity_key": f"person:{pid}", "scenario_id": baseline_sid, "scenario_role": "background"}
        )

    # 2) explicit suspicious motifs
    suspicious_sid = _new_scenario(
        scenario_registry,
        "explicit_suspicious_motif",
        "suspicious",
        "Shared bank accounts across distant addresses, concentrated claims, and agent-claimant overlap.",
    )
    sus_people_list = list(suspicious_people)
    rng.shuffle(sus_people_list)
    clusters = [sus_people_list[i:i + 4] for i in range(0, len(sus_people_list), 4)]
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        bank = banks[rng.randrange(0, len(banks))]["RES_BANK_ACCOUNT_ID"]
        shared_policy = _pick(rng, policy_numbers)
        writing_agent = cluster[0]
        for pid in cluster:
            # force many claims on one policy
            for _ in range(rng.randint(1, 2)):
                cid = f"C{9000000001 + len(claims)}"
                p = people_by_id[pid]
                claims.append(
                    {
                        "CLAIM_ID": cid,
                        "CLAIM_NUMBER": f"CLM-2025-{10000 + len(claims):05d}",
                        "POLICY_NUMBER": shared_policy,
                        "FIRST_NAME": p["FIRST_NAME"],
                        "LAST_NAME": p["LAST_NAME"],
                        "BIRTH_DATE": p["BIRTH_DATE"],
                        "CLAIM_OPEN_DATE": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                        "CLAIM_CLOSE_DATE": "",
                        "CLAIM_STATUS_CODE": "OPEN",
                        "CLAIM_VALID_IND": 1,
                        "CLAIM_SYSTEM": "SYS01",
                    }
                )
                entity_scenario_map.append(
                    {"entity_type": "Claim", "entity_key": f"claim:{cid}", "scenario_id": suspicious_sid, "scenario_role": "clustered_claim"}
                )
            person_bank.append({"RES_BANK_ACCOUNT_ID": bank, "EDGE_NAME": "HOLD_BY", "RES_PERSON_ID": pid})
            edge_scenario_map.append(
                {
                    "edge_type": "HOLD_BY",
                    "source_key": f"person:{pid}",
                    "target_key": f"bank:{bank}",
                    "scenario_id": suspicious_sid,
                    "scenario_role": "shared_bank_cluster",
                }
            )
            entity_scenario_map.append(
                {"entity_type": "Person", "entity_key": f"person:{pid}", "scenario_id": suspicious_sid, "scenario_role": "suspicious_actor"}
            )
            person_policy.append(
                {
                    "RES_PERSON_ID": pid,
                    "EDGE_NAME": "IS_COVERED_BY",
                    "EDGE_DETAIL": "",
                    "EDGE_DETAIL_DSC": "",
                    "POLICY_NUMBER": shared_policy,
                }
            )
        person_policy.append(
            {
                "RES_PERSON_ID": writing_agent,
                "EDGE_NAME": "SOLD_POLICY",
                "EDGE_DETAIL": "WRITING_AGENT",
                "EDGE_DETAIL_DSC": "AGENT",
                "POLICY_NUMBER": shared_policy,
            }
        )

    # 3) ambiguous / weak-signal motifs
    ambiguous_sid = _new_scenario(
        scenario_registry,
        "ambiguous_weak_signal",
        "ambiguous",
        "Cross-household but plausible support ties and mixed-status policy activity.",
    )
    for pid in ambiguous_people:
        # add second address (temporal ambiguity)
        aid = addresses[rng.randrange(0, len(addresses))]["RES_ADDRESS_ID"]
        person_address.append(
            {
                "RES_PERSON_ID": pid,
                "EDGE_NAME": "LOCATED_IN",
                "EFFECTIVE_DATE": "2024-07-01",
                "IS_LATEST_ADDRESS_IND": 0,
                "RES_ADDRESS_ID": aid,
            }
        )
        entity_scenario_map.append(
            {"entity_type": "Person", "entity_key": f"person:{pid}", "scenario_id": ambiguous_sid, "scenario_role": "multi_address"}
        )
        edge_scenario_map.append(
            {
                "edge_type": "LOCATED_IN",
                "source_key": f"person:{pid}",
                "target_key": f"address:{aid}",
                "scenario_id": ambiguous_sid,
                "scenario_role": "historical_or_ambiguous_address",
            }
        )

    # 4) structurally unusual anomaly bridges
    bridge_sid = _new_scenario(
        scenario_registry,
        "structural_bridge_anomaly",
        "ambiguous",
        "Bridge-like links between otherwise separate clusters via policy and social edges.",
    )
    amb_list = list(ambiguous_people)
    for _ in range(max(3, len(amb_list) // 10)):
        if len(amb_list) < 2:
            break
        src, tgt = rng.sample(amb_list, 2)
        person_person.append(
            {
                "RES_PERSON_ID_SRC": src,
                "EDGE_NAME": "ACT_ON_BEHALF_OF",
                "EDGE_DETAIL": "CARE_PROXY",
                "EDGE_DETAIL_DSC": "LEGAL",
                "RES_PERSON_ID_TGT": tgt,
            }
        )
        edge_scenario_map.append(
            {
                "edge_type": "ACT_ON_BEHALF_OF",
                "source_key": f"person:{src}",
                "target_key": f"person:{tgt}",
                "scenario_id": bridge_sid,
                "scenario_role": "bridge_link",
            }
        )
        entity_scenario_map.append(
            {"entity_type": "Person", "entity_key": f"person:{src}", "scenario_id": bridge_sid, "scenario_role": "bridge_endpoint"}
        )
        entity_scenario_map.append(
            {"entity_type": "Person", "entity_key": f"person:{tgt}", "scenario_id": bridge_sid, "scenario_role": "bridge_endpoint"}
        )

    # Keep requested claim volume stable
    if len(claims) > claims_n:
        claims = claims[:claims_n]

    # Force known demo-friendly IDs
    if len(claims) >= 2:
        claims[1]["CLAIM_ID"] = "C9000000002"
        claims[1]["CLAIM_NUMBER"] = "CLM-2024-00102"

    return {
        "t_resolved_person": pd.DataFrame(people),
        "t_resolved_business": pd.DataFrame(businesses),
        "t_norm_policy": pd.DataFrame(policies),
        "t_norm_claim": pd.DataFrame(claims),
        "t_resolved_address": pd.DataFrame(addresses),
        "t_resolved_bank_account": pd.DataFrame(banks),
        "t_resolved_person_address_crosswalk": pd.DataFrame(person_address),
        "t_resolved_business_address_crosswalk": pd.DataFrame(business_address),
        "t_resolved_person_person_crosswalk": pd.DataFrame(person_person),
        "t_resolved_person_policy_crosswalk": pd.DataFrame(person_policy),
        "t_resolved_person_bank_account_crosswalk": pd.DataFrame(person_bank),
        "scenario_registry": pd.DataFrame(scenario_registry),
        "entity_scenario_map": pd.DataFrame(entity_scenario_map),
        "edge_scenario_map": pd.DataFrame(edge_scenario_map),
    }


def validate_operational_data(data: dict[str, pd.DataFrame]) -> None:
    people = set(data["t_resolved_person"]["RES_PERSON_ID"])
    address = set(data["t_resolved_address"]["RES_ADDRESS_ID"])
    business = set(data["t_resolved_business"]["RES_BUSINESS_ID"])
    policy = set(data["t_norm_policy"]["POLICY_NUMBER"])
    bank = set(data["t_resolved_bank_account"]["RES_BANK_ACCOUNT_ID"])

    pa = data["t_resolved_person_address_crosswalk"]
    assert set(pa["RES_PERSON_ID"]).issubset(people)
    assert set(pa["RES_ADDRESS_ID"]).issubset(address)

    ba = data["t_resolved_business_address_crosswalk"]
    assert set(ba["RES_BUSINESS_ID"]).issubset(business)
    assert set(ba["RES_ADDRESS_ID"]).issubset(address)

    pp = data["t_resolved_person_person_crosswalk"]
    assert set(pp["RES_PERSON_ID_SRC"]).issubset(people)
    assert set(pp["RES_PERSON_ID_TGT"]).issubset(people)

    ppol = data["t_resolved_person_policy_crosswalk"]
    assert set(ppol["RES_PERSON_ID"]).issubset(people)
    assert set(ppol["POLICY_NUMBER"]).issubset(policy)

    pbank = data["t_resolved_person_bank_account_crosswalk"]
    assert set(pbank["RES_PERSON_ID"]).issubset(people)
    assert set(pbank["RES_BANK_ACCOUNT_ID"]).issubset(bank)

    claims = data["t_norm_claim"]
    assert set(claims["POLICY_NUMBER"]).issubset(policy)


def write_dataset(data: dict[str, pd.DataFrame], config: GenerationConfig) -> None:
    config.output_seed_dir.mkdir(parents=True, exist_ok=True)
    config.output_eval_dir.mkdir(parents=True, exist_ok=True)

    operational = [
        "t_resolved_person",
        "t_resolved_business",
        "t_norm_policy",
        "t_norm_claim",
        "t_resolved_address",
        "t_resolved_bank_account",
        "t_resolved_person_address_crosswalk",
        "t_resolved_business_address_crosswalk",
        "t_resolved_person_person_crosswalk",
        "t_resolved_person_policy_crosswalk",
        "t_resolved_person_bank_account_crosswalk",
    ]
    for name in operational:
        data[name].to_csv(config.output_seed_dir / f"{name}.csv", index=False, encoding="utf-8")

    data["scenario_registry"].to_csv(config.output_eval_dir / "scenario_registry.csv", index=False, encoding="utf-8")
    data["entity_scenario_map"].to_csv(config.output_eval_dir / "entity_scenario_map.csv", index=False, encoding="utf-8")
    data["edge_scenario_map"].to_csv(config.output_eval_dir / "edge_scenario_map.csv", index=False, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reproducible synthetic seed + hidden eval metadata.")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "src" / "synthetic" / "configs" / "large.yaml"),
        help="Path to YAML config file.",
    )
    args = parser.parse_args()

    cfg = _load_config(Path(args.config).resolve())
    data = generate_dataset(cfg)
    validate_operational_data(data)
    write_dataset(data, cfg)

    total_nodes_est = sum(cfg.target_counts.values())
    print(f"Generated synthetic dataset with target ~{total_nodes_est} nodes")
    print(f"Operational seed CSVs: {cfg.output_seed_dir}")
    print(f"Hidden eval metadata: {cfg.output_eval_dir}")


if __name__ == "__main__":
    main()


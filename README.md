# GridWise AI: Carbon-Aware Compute Scheduler

**Idea:**  
An AI-powered scheduler that shifts flexible AI and data-center workloads into lower-carbon hours using real grid emissions data and optimization, cutting compute emissions without missing SLAs.

## What this project is

GridWise AI is a carbon-aware scheduling platform for flexible compute jobs. Given a workload’s region, duration, power draw, and deadline, it finds the cleanest feasible time window to run that job and compares it against the baseline “run now” option.

## Why we are building this

AI buildout is increasing demand on the grid, and data centers are becoming a meaningful driver of electricity growth. In 2025, global electricity demand grew 3%, with EVs and data centers among the fastest-growing contributors, and data centers accounted for around half of total electricity demand growth in the U.S.

At the same time, grid emissions are not constant throughout the day. Hourly carbon intensity can change significantly depending on generation mix, imports, and system conditions, which means the timing of a workload directly affects its emissions footprint.

That creates a clear opportunity: **same compute, smarter timing**. Instead of changing the job itself, GridWise AI changes *when* it runs so flexible workloads align with lower-carbon hours while still meeting deadlines.

## Problem

Many AI and batch-compute workloads are flexible, but they still run during fossil-heavy peak periods by default. That adds avoidable emissions and often increases pressure on already-constrained evening demand windows.

## Solution

GridWise AI takes a workload input, pulls real hourly grid-carbon data, and uses optimization to schedule that workload in the lowest-carbon feasible window before its deadline. It then shows the user the recommended schedule, baseline vs optimized emissions, percent reduction, and a short explanation of why the new schedule is better.

## What we built

- Input form for region, duration, kWh / power draw, and deadline
- Real grid-carbon data integration using Electricity Maps or WattTime
- Optimization engine that compares baseline vs best feasible schedule
- Output showing recommended window, kg CO2 avoided, and % emissions reduction
- Lightweight AI explanation layer to summarize the decision in plain language

## Motivation

This project is based on a simple idea:  
**more AI compute on the grid can mean more emissions, but carbon-aware scheduling can reduce those emissions without reducing compute.**

The broader goal is to make energy-aware software practical. Instead of asking operators to manually reason about grid behavior, GridWise AI turns live carbon signals into an actionable scheduling recommendation.

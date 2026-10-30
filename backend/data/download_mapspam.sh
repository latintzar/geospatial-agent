#!/bin/bash
# Download MapSPAM 2020 data for Leo
# Run this script once to get the crop production data

echo "📥 Downloading MapSPAM 2020 Global Data..."
echo "This is ~2.3GB and may take a while..."

cd "$(dirname "$0")"

# Create directories
mkdir -p mapspam/spam2020V2r0_global_production
mkdir -p mapspam/spam2020V2r0_global_harvested_area
mkdir -p mapspam/spam2020V2r0_global_physical_area
mkdir -p mapspam/spam2020V2r0_global_yield

# MapSPAM download URLs (from IFPRI)
BASE_URL="https://s3.amazonaws.com/mapspam/2020/v2r0/csv"

echo ""
echo "Downloading Production data..."
curl -L -o mapspam/spam2020V2r0_global_production/spam2020V2r0_global_P_TA.csv "$BASE_URL/spam2020V2r0_global_P_TA.csv"
curl -L -o mapspam/spam2020V2r0_global_production/spam2020V2r0_global_P_TI.csv "$BASE_URL/spam2020V2r0_global_P_TI.csv"
curl -L -o mapspam/spam2020V2r0_global_production/spam2020V2r0_global_P_TR.csv "$BASE_URL/spam2020V2r0_global_P_TR.csv"

echo ""
echo "Downloading Harvested Area data..."
curl -L -o mapspam/spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TA.csv "$BASE_URL/spam2020V2r0_global_H_TA.csv"
curl -L -o mapspam/spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TI.csv "$BASE_URL/spam2020V2r0_global_H_TI.csv"
curl -L -o mapspam/spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TR.csv "$BASE_URL/spam2020V2r0_global_H_TR.csv"

echo ""
echo "Downloading Physical Area data..."
curl -L -o mapspam/spam2020V2r0_global_physical_area/spam2020V2r0_global_A_TA.csv "$BASE_URL/spam2020V2r0_global_A_TA.csv"
curl -L -o mapspam/spam2020V2r0_global_physical_area/spam2020V2r0_global_A_TI.csv "$BASE_URL/spam2020V2r0_global_A_TI.csv"
curl -L -o mapspam/spam2020V2r0_global_physical_area/spam2020V2r0_global_A_TR.csv "$BASE_URL/spam2020V2r0_global_A_TR.csv"

echo ""
echo "Downloading Yield data..."
curl -L -o mapspam/spam2020V2r0_global_yield/spam2020V2r0_global_Y_TA.csv "$BASE_URL/spam2020V2r0_global_Y_TA.csv"
curl -L -o mapspam/spam2020V2r0_global_yield/spam2020V2r0_global_Y_TI.csv "$BASE_URL/spam2020V2r0_global_Y_TI.csv"
curl -L -o mapspam/spam2020V2r0_global_yield/spam2020V2r0_global_Y_TR.csv "$BASE_URL/spam2020V2r0_global_Y_TR.csv"

echo ""
echo "✅ MapSPAM data downloaded successfully!"
echo "Data location: $(pwd)/mapspam/"


// Convert Google Sheets CSV to JSON format for dashboard
async function convertGoogleSheetData() {
  const csvUrl = "https://docs.google.com/spreadsheets/d/1AxmpCZhsQ-rFAJkgYrTbPby6FEG8HHkbL60IStUl-ak/export?format=csv";
  
  const response = await fetch(csvUrl);
  const csv = await response.text();
  const lines = csv.split('\n').slice(1); // Skip header
  
  const data = lines.map(line => {
    const cols = line.split(',').map(c => c.trim());
    return [
      cols[0],  // 0: District
      cols[1],  // 1: Tehsil
      cols[2],  // 2: Markaz
      cols[3],  // 3: Wing
      cols[5],  // 4: EMIS
      cols[6],  // 5: School
      parseInt(cols[12]) || 0,  // 6: Baseline
      parseInt(cols[16]) || 0,  // 7: Current
      parseInt(cols[17]) || 0,  // 8: Target
      parseInt(cols[21]) || 0,  // 9: Previous
      parseInt(cols[13]) || 0   // 10: New Target (Column N)
    ];
  }).filter(r => r[0]); // Remove empty rows
  
  return data;
}

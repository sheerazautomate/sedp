// Convert Google Sheets CSV to JSON format for dashboard
async function convertGoogleSheetData() {
  const csvUrl = "https://docs.google.com/spreadsheets/d/1AxmpCZhsQ-rFAJkgYrTbPby6FEG8HHkbL60IStUl-ak/export?format=csv"; // Paste your CSV URL here
  
  const response = await fetch(csvUrl);
  const csv = await response.text();
  const lines = csv.split('\n').slice(1); // Skip header
  
  const data = lines.map(line => {
    const cols = line.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/).map(c => {
      let val = c.trim();
      if (val.startsWith('"') && val.endsWith('"')) {
        val = val.substring(1, val.length - 1).trim();
      }
      return val;
    });
    
    return [
      cols[0],  // District (0)
      cols[1],  // Tehsil (1)
      cols[2],  // Markaz (2)
      cols[3],  // Wing (3)
      cols[5],  // EMIS (4)
      cols[6],  // School (5)
      parseInt(cols[12]) || 0,  // Baseline (6)
      parseInt(cols[16]) || 0,  // Current (7)
      parseInt(cols[17]) || 0,  // Target (8)
      parseInt(cols[21]) || 0,  // Previous (9)
      parseInt(cols[13]) || 0   // New Target (10) - Column N
    ];
  }).filter(r => r[0]); // Remove empty rows
  
  return data;
}

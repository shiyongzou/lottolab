function zoneNums(draw, zone) {
  return zone === 'a' ? draw.a : draw.b;
}

function frequency(drawList, zone, range) {
  const freq = new Array(range + 1).fill(0);
  for (const d of drawList) for (const n of zoneNums(d, zone)) freq[n]++;
  return freq;
}

function currentOmission(drawList, zone, range) {
  const om = new Array(range + 1).fill(drawList.length);
  for (let n = 1; n <= range; n++) {
    for (let i = 0; i < drawList.length; i++) {
      if (zoneNums(drawList[i], zone).includes(n)) { om[n] = i; break; }
    }
  }
  return om;
}

function sumSeries(drawList, count) {
  return drawList
    .slice(0, count)
    .map((d) => d.a.reduce((s, n) => s + n, 0))
    .reverse();
}

function oddCountDist(drawList, pick) {
  const dist = new Array(pick + 1).fill(0);
  for (const d of drawList) {
    dist[d.a.filter((n) => n % 2 === 1).length]++;
  }
  return dist;
}

function consecutivePairs(nums) {
  let c = 0;
  for (let i = 1; i < nums.length; i++) if (nums[i] - nums[i - 1] === 1) c++;
  return c;
}

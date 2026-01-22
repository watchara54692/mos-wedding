let page = 1;
let loading = false;

async function loadCustomers() {
  if (loading) return;
  loading = true;

  showSkeleton();

  const res = await fetch(`/customers?page=${page}&limit=20`);
  const json = await res.json();

  hideSkeleton();

  json.data.forEach(c => renderCustomer(c));

  if (page < json.total_pages) {
    page++;
  }

  loading = false;
}

function showSkeleton() {
  document.getElementById("loading").style.display = "block";
}

function hideSkeleton() {
  document.getElementById("loading").style.display = "none";
}

function renderCustomer(c) {
  const div = document.createElement("div");
  div.className = "customer";
  div.innerHTML = `
    <b>${c.name}</b><br>
    ${c.phone}<br>
    <small>${new Date(c.created_at).toLocaleString()}</small>
  `;
  document.getElementById("list").appendChild(div);
}


// โหลดครั้งแรก
loadCustomers();


// infinite scroll
window.addEventListener("scroll", () => {
  if (
    window.innerHeight + window.scrollY
    >= document.body.offsetHeight - 200
  ) {
    loadCustomers();
  }
});

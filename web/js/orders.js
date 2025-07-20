const apiBase = 'http://localhost:9090';

// 获取方案列表
function loadSchemes() {
  axios.get(`${apiBase}/schemes`)
    .then(res => {
      const select = document.getElementById("schemeSelect");
      select.innerHTML = res.data.map(item =>
        `<option value="${item.name}">${item.name}</option>`
      ).join("");

      // 添加“自选”选项
      const customOption = document.createElement("option");
      customOption.value = "__custom__";
      customOption.textContent = "自选";
      select.appendChild(customOption);
    });
}

// 创建订单
function createOrder() {
  const username = document.getElementById("username").value;
  const price = parseInt(document.getElementById("price").value, 10);
  const selectedScheme = document.getElementById("schemeSelect").value;

  let schemeName = selectedScheme;
  if (selectedScheme === "__custom__") {
    const customInput = document.getElementById("customNumber");
    const customValue = customInput.value.trim();
    if (!customValue) {
      alert("请输入自选号码");
      return;
    }
    schemeName = customValue;
  }

  axios.post(`${apiBase}/orders`, { username: username, scheme_name: schemeName, price: price })
    .then(() => {
      loadOrders();
      alert("下单成功");
    });
}

// 获取订单列表
function loadOrders() {
  axios.get(`${apiBase}/orders`)
    .then(res => {
      const tbody = document.querySelector("#orderTable tbody");
      tbody.innerHTML = res.data.map(item =>
        `<tr>
    <td>${item.id}</td>
    <td>${item.username}</td>
    <td>${item.scheme_name}</td>
    <td>${item.price}</td>
    <td>${item.create_at}</td>
  </tr>`
      ).join("");
    });
}

// 显示/隐藏自选号码输入框
function setupSchemeSelectListener() {
  const schemeSelect = document.getElementById("schemeSelect");
  const customInput = document.getElementById("customNumber");

  schemeSelect.addEventListener("change", () => {
    if (schemeSelect.value === "__custom__") {
      customInput.style.display = "block";
    } else {
      customInput.style.display = "none";
    }
  });
}

window.onload = () => {
  loadSchemes();
  loadOrders();
  setupSchemeSelectListener();
};

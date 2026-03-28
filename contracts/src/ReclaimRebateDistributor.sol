// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Reclaim Rebate Distributor
/// @notice Distributes MEV rebates to users and tracks referrals for reclaimfi.xyz
contract ReclaimRebateDistributor {
    address public owner;

    mapping(address => address) public referrers;
    mapping(address => uint256) public totalRebates;
    mapping(address => uint256) public referralEarnings;
    mapping(address => uint256) public referralCount;

    uint256 public totalDistributed;

    event RebatePaid(address indexed user, uint256 amount);
    event ReferralPaid(address indexed referrer, address indexed referred, uint256 amount);
    event ReferralRegistered(address indexed user, address indexed referrer);
    event OwnershipTransferred(address indexed prev, address indexed next);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice User registers who referred them (one-time)
    function registerReferrer(address referrer) external {
        require(referrers[msg.sender] == address(0), "Already registered");
        require(referrer != msg.sender, "Self-referral");
        require(referrer != address(0), "Zero address");
        referrers[msg.sender] = referrer;
        referralCount[referrer]++;
        emit ReferralRegistered(msg.sender, referrer);
    }

    /// @notice Owner distributes rebates in batch (saves gas vs individual sends)
    function batchDistribute(
        address[] calldata users,
        uint256[] calldata amounts
    ) external payable onlyOwner {
        require(users.length == amounts.length, "Length mismatch");

        uint256 total;
        for (uint256 i; i < users.length; i++) {
            if (amounts[i] == 0) continue;
            total += amounts[i];
            (bool ok, ) = users[i].call{value: amounts[i]}("");
            if (ok) {
                totalRebates[users[i]] += amounts[i];
                emit RebatePaid(users[i], amounts[i]);
            }
        }
        totalDistributed += total;
    }

    /// @notice Owner distributes referral earnings in batch
    function batchReferralPay(
        address[] calldata referrersList,
        address[] calldata referred,
        uint256[] calldata amounts
    ) external payable onlyOwner {
        require(
            referrersList.length == amounts.length && referred.length == amounts.length,
            "Length mismatch"
        );

        for (uint256 i; i < referrersList.length; i++) {
            if (amounts[i] == 0) continue;
            (bool ok, ) = referrersList[i].call{value: amounts[i]}("");
            if (ok) {
                referralEarnings[referrersList[i]] += amounts[i];
                emit ReferralPaid(referrersList[i], referred[i], amounts[i]);
            }
        }
    }

    /// @notice Dashboard view function — returns all user stats in one call
    function getUserStats(address user) external view returns (
        uint256 totalEarned,
        uint256 referralIncome,
        address referredBy,
        uint256 numReferrals
    ) {
        return (
            totalRebates[user],
            referralEarnings[user],
            referrers[user],
            referralCount[user]
        );
    }

    /// @notice Withdraw any remaining balance to owner
    function withdraw() external onlyOwner {
        (bool ok, ) = owner.call{value: address(this).balance}("");
        require(ok, "Transfer failed");
    }

    /// @notice Transfer ownership
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    receive() external payable {}
}
